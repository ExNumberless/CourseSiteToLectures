import json
import socket
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from coursesitetolectures import CoursePlugin
from coursesitetolectures.providers import urlcheck
from coursesitetolectures.providers.urlcheck import BlockedURL, public_only
from coursesitetolectures.providers.web import Web
from coursesitetolectures.providers.website import Fetcher, WebsiteProvider

METADATA_URL = "http://169.254.169.254/latest/meta-data/"


class Handler(BaseHTTPRequestHandler):
    """Serves the server's {path: (status, headers, body)}; anything else is a 404."""

    def do_GET(self):
        self.server.requests.append(self.path)
        status, headers, body = self.server.routes.get(self.path, (404, {}, b""))
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    """An HTTP server on 127.0.0.1, so no test leaves the machine."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.routes, httpd.requests = {}, []
    httpd.url = f"http://127.0.0.1:{httpd.server_port}"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def redirect(location):
    return 302, {"Location": location}, b""


def page(body, content_type="text/html"):
    return 200, {"Content-Type": content_type}, body


def local_or_public(server, seen=None):
    """A validator that allows the test server and otherwise acts as public_only, recording URLs."""

    def validate(url):
        if seen is not None:
            seen.append(url)
        if urlsplit(url).netloc != urlsplit(server.url).netloc:
            public_only(url)

    return validate


@pytest.fixture(autouse=True)
def no_dns(monkeypatch):
    """Resolve IP literals only; tests that need names stub getaddrinfo with fake_dns."""
    real = socket.getaddrinfo

    def getaddrinfo(host, port, *args, **kwargs):
        return real(host, port, *args, flags=socket.AI_NUMERICHOST, **{k: v for k, v in kwargs.items() if k != "flags"})

    monkeypatch.setattr(urlcheck.socket, "getaddrinfo", getaddrinfo)


def fake_dns(monkeypatch, names):
    def getaddrinfo(host, port, *args, **kwargs):
        if host not in names:
            raise socket.gaierror(socket.EAI_NONAME, "unknown name")
        return [
            (socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in names[host]
        ]

    monkeypatch.setattr(urlcheck.socket, "getaddrinfo", getaddrinfo)


@pytest.mark.parametrize(
    "url",
    [
        METADATA_URL,
        "http://[fd00:ec2::254]/latest/meta-data/",
        "http://100.100.100.200/",
        "http://127.0.0.1:8000/",
        "http://[::1]/",
        "http://10.1.2.3/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://100.64.0.1/",  # carrier-grade NAT
        "http://0.0.0.0/",
        "http://169.254.1.1/",
        "http://[fe80::1]/",
        "http://224.0.0.1/",
        "http://[ff02::1]/",
        "http://240.0.0.1/",
        "http://255.255.255.255/",
        "http://[::ffff:127.0.0.1]/",  # IPv4-mapped
        "http://[2002:a9fe:a9fe::]/",  # 6to4 wrapping 169.254.169.254
        "http://[64:ff9b::a00:1]/",  # NAT64 wrapping 10.0.0.1
        "http://[fc00::1]/",
        "http://2130706433/",  # 127.0.0.1 as a number
        "file:///etc/passwd",
        "ftp://example.com/",
        "http:///nohost",
    ],
)
def test_public_only_blocks(url):
    with pytest.raises(BlockedURL):
        public_only(url)


@pytest.mark.parametrize("url", ["http://93.184.215.14/", "https://[2606:4700::1111]/x", "http://8.8.8.8:8080/"])
def test_public_only_allows_public_addresses(url):
    public_only(url)


def test_public_only_resolves_names(monkeypatch):
    fake_dns(
        monkeypatch,
        {
            "example.edu": ["93.184.215.14", "2606:4700::1111"],
            "metadata.google.internal": ["169.254.169.254"],
            "sneaky.example": ["93.184.215.14", "10.0.0.5"],  # any blocked address refuses the URL
        },
    )
    public_only("https://example.edu/course/")
    with pytest.raises(BlockedURL, match="169.254.169.254"):
        public_only("http://metadata.google.internal/computeMetadata/v1/")
    with pytest.raises(BlockedURL, match="10.0.0.5"):
        public_only("http://sneaky.example/")
    with pytest.raises(urllib.error.URLError) as e:
        public_only("http://nowhere.invalid/")
    assert not isinstance(e.value, BlockedURL)  # a lookup failure is retried like other errors


def test_default_allows_everything_and_follows_redirects(server):
    server.routes = {"/a": redirect("/b"), "/b": page(b"hello")}
    response = Web(delay=0).get(server.url + "/a")
    assert (response.url, response.content) == (server.url + "/b", b"hello")


def test_redirect_to_blocked_address_is_refused(server, monkeypatch):
    server.routes = {"/start": redirect("/hop"), "/hop": redirect(METADATA_URL)}
    monkeypatch.setattr("time.sleep", lambda s: pytest.fail("a blocked URL shouldn't be retried"))
    seen = []
    web = Web(delay=0, attempts=4, validate_url=local_or_public(server, seen))
    with pytest.raises(BlockedURL) as e:
        web.get(server.url + "/start")
    assert e.value.url == METADATA_URL
    start, robots, hop = (server.url + p for p in ("/start", "/robots.txt", "/hop"))
    assert seen == [robots, start, hop, METADATA_URL]  # the redirect target is checked before following it
    assert METADATA_URL in str(e.value)
    assert server.requests == ["/robots.txt", "/start", "/hop"]


def test_blocked_url_is_never_requested(server):
    def validate(url):
        raise BlockedURL(url, "no")

    with pytest.raises(BlockedURL):
        Web(delay=0, validate_url=validate).get(server.url + "/")
    assert server.requests == []


def test_wayback_and_drive_urls_are_validated(monkeypatch):
    """Archive lookups and Google fallbacks go through the validator like any other URL."""
    seen = []

    def validate(url):
        seen.append(url)
        raise BlockedURL(url, "offline test")

    web = Web(delay=0, validate_url=validate)
    fetcher = Fetcher(web, "https://example.edu/course/", "2019")  # looks up the CDX index
    with pytest.raises(urllib.error.URLError):
        fetcher.download(
            "https://drive.google.com/open?id=XYZ", "drive", ["https://drive.google.com/uc?export=download&id=XYZ"]
        )
    assert any(u.startswith("https://web.archive.org/cdx/") for u in seen)
    assert "https://drive.google.com/uc?export=download&id=XYZ" in seen
    assert any("docs.google.com%2Fpresentation%2Fd%2FXYZ" in u for u in seen)  # the deleted-deck lookup


def test_fetch_skips_blocked_links(server, tmp_path, capsys):
    schedule = b"""<html><head><title>Course</title></head><body><table>
    <tr><th>Lecture</th></tr>
    <tr><td>Intro <a href="/intro.pdf">slides</a> <a href="/moved.pdf">notes</a>
        <a href="http://10.0.0.1/secret.pdf">internal</a></td></tr>
    </table></body></html>"""
    server.routes = {
        "/course/": page(schedule),
        "/intro.pdf": page(b"%PDF-1.4 intro", "application/pdf"),
        "/moved.pdf": redirect(METADATA_URL + "x.pdf"),
    }
    plugin = CoursePlugin()
    plugin.fetch_delay = 0
    WebsiteProvider().fetch(plugin, server.url + "/course/", tmp_path, validate_url=local_or_public(server))
    lecture = json.loads((tmp_path / "lectures.json").read_text())["lectures"][0]
    assert lecture["files"] == ["files/lecture-01/intro.pdf"]
    err = capsys.readouterr().err
    assert "couldn't fetch http://10.0.0.1/secret.pdf" in err and "non-public address (10.0.0.1)" in err
    assert f"couldn't fetch {server.url}/moved.pdf" in err and "169.254.169.254" in err


def test_fetch_raises_when_the_course_page_is_blocked(tmp_path):
    with pytest.raises(BlockedURL):
        WebsiteProvider().fetch(CoursePlugin(), "http://192.168.0.10/course/", tmp_path, validate_url=public_only)
