"""A small, polite HTTP client for online providers, with Wayback Machine support.

Requests identify the tool in their User-Agent, follow each site's robots.txt, wait between
requests to the same host, and retry rate limits and server errors with backoff.
"""

import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from email.message import Message

from .. import __version__

USER_AGENT = f"coursesitetolectures/{__version__} (+https://github.com/ExNumberless/CourseSiteToLectures)"
WAYBACK = re.compile(r"^https?://web\.archive\.org/web/(\d+)[a-z_]*/(.+)$")
RETRY_STATUSES = {429, 500, 502, 503, 504}
# Hosts that need more time between requests. The Wayback Machine refuses connections for a while
# from clients that request faster than about 15 a minute.
HOST_DELAYS = {"web.archive.org": 4.0}
REFUSED_WAIT = 60  # seconds, growing with each attempt, after a refused connection


@dataclass
class Response:
    url: str  # after redirects
    content: bytes
    content_type: str
    filename: str | None  # from Content-Disposition


def unwrap(url):
    """(Wayback timestamp, original URL) for a web.archive.org URL, else (None, url)."""
    if m := WAYBACK.match(url):
        original = m.group(2)
        if not re.match(r"^https?://", original):
            original = "http://" + original.removeprefix("http:/").removeprefix("https:/").lstrip("/")
        return m.group(1), original
    return None, url


def archived(timestamp, url):
    """The Wayback Machine's raw capture of url nearest timestamp (no archive toolbar or rewriting)."""
    return f"https://web.archive.org/web/{timestamp}id_/{url}"


class Web:
    def __init__(self, delay=1.0, attempts=4, timeout=60):
        self.delay, self.attempts, self.timeout = delay, attempts, timeout
        self.last = {}  # host -> time of the last request
        self.robots = {}  # origin -> RobotFileParser, or None if robots.txt couldn't be read

    def allowed(self, url):
        parts = urllib.parse.urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.robots:
            parser = urllib.robotparser.RobotFileParser()
            try:
                parser.parse(self._open(f"{origin}/robots.txt").content.decode(errors="replace").splitlines())
            except (urllib.error.URLError, OSError):
                parser = None
            self.robots[origin] = parser
        parser = self.robots[origin]
        return parser is None or parser.can_fetch(USER_AGENT, url)

    def _wait(self, host):
        pause = self.last.get(host, 0) + max(self.delay, HOST_DELAYS.get(host, 0)) - time.monotonic()
        if pause > 0:
            time.sleep(pause)
        self.last[host] = time.monotonic()

    def _open(self, url):
        self._wait(urllib.parse.urlsplit(url).netloc)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=self.timeout) as r:
            disposition = Message()
            disposition["Content-Disposition"] = r.headers.get("Content-Disposition", "")
            filename = disposition.get_filename()
            return Response(r.geturl(), r.read(), r.headers.get_content_type(), filename)

    def get(self, url):
        """GET url, raising urllib.error.HTTPError or URLError on failure."""
        if not self.allowed(url):
            raise urllib.error.URLError(f"disallowed by robots.txt: {url}")
        for attempt in range(self.attempts):
            try:
                return self._open(url)
            except urllib.error.HTTPError as e:
                if e.code not in RETRY_STATUSES or attempt == self.attempts - 1:
                    raise
                retry_after = e.headers.get("Retry-After", "")
                time.sleep(float(retry_after) if retry_after.isdigit() else 2 ** (attempt + 1))
            except urllib.error.URLError as e:
                if attempt == self.attempts - 1:
                    raise
                refused = isinstance(e.reason, ConnectionRefusedError)
                time.sleep(REFUSED_WAIT * (attempt + 1) if refused else 2 ** (attempt + 1))
        raise AssertionError("unreachable")
