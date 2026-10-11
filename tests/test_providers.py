import json
import urllib.error
from pathlib import Path

import pymupdf
import pytest
from bs4 import BeautifulSoup

from coursesitetolectures import CoursePlugin, Provider, cli, providers
from coursesitetolectures.providers.web import Response, archived, unwrap
from coursesitetolectures.providers.website import WebsiteProvider, cell_title, classify, table_grid

SITE = "https://inst.eecs.berkeley.edu/~cs61a/su19/"
SCHEDULE = """<html><head><title>CS 61A Summer 2019</title></head><body>
<table>
<tr><th>Week</th><th>Date</th><th>Lecture</th><th>Textbook</th><th>Lab and Discussion</th></tr>
<tr><td rowspan="2">1</td><td>Mon 6/24</td>
    <td>Intro <a href="https://docs.google.com/presentation/d/AAA/edit?usp=sharing">slides</a>
        <a href="https://youtu.be/xyz">Video</a> <a href="assets/slides/01.py">01.py</a></td>
    <td></td><td><a href="lab/lab00/">Lab 00</a></td></tr>
<tr><td>Tue 6/25</td>
    <td>Functions <a href="https://docs.google.com/presentation/d/GONE/edit">slides</a>
        <a href="assets/slides/02.py">02.py</a> <a href="https://forms.gle/x">Survey</a></td>
    <td><a href="http://composingprograms.com/pages/11-getting-started.html">Ch. 1.1</a></td>
    <td><a href="disc/disc00.pdf">Disc 00</a></td></tr>
<tr><td>2</td><td>Mon 7/1</td><td>No lecture</td><td></td><td></td></tr>
</table></body></html>"""


def pdf_bytes(text):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    return doc.tobytes()


class FakeWeb:
    """Serves a dict of {url: Response or bytes}; anything else is a 404."""

    def __init__(self, pages):
        self.pages, self.requests = pages, []

    def get(self, url):
        self.requests.append(url)
        page = self.pages.get(url)
        if page is None:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if isinstance(page, bytes):
            return Response(url, page, "application/octet-stream", None)
        return page


def site_pages(prefix=""):
    def url(u):
        return prefix + u if prefix and u.startswith(SITE) else u

    return {
        url(SITE): Response(url(SITE), SCHEDULE.encode(), "text/html", None),
        "https://docs.google.com/presentation/d/AAA/export/pdf": Response(
            "x", pdf_bytes("Welcome to 61A"), "application/pdf", "01 - Intro.pdf"
        ),
        url(SITE + "assets/slides/01.py"): b"print('hi')\n",
        url(SITE + "assets/slides/02.py"): b"def square(x):\n    return x * x\n",
    }


def test_table_grid_expands_rowspan():
    soup = BeautifulSoup(SCHEDULE, "html.parser")
    grid = table_grid(soup.find("table"))
    assert [len(row) for row in grid] == [5, 5, 5, 5]
    assert grid[2][0] is grid[1][0]  # the week cell spans two rows
    assert grid[2][2].get_text().split()[0] == "Functions"


@pytest.mark.parametrize(
    "url, kind",
    [
        ("https://docs.google.com/presentation/d/AAA/edit#slide=id.p", "slides"),
        ("https://docs.google.com/document/d/BBB/edit", "document"),
        ("https://youtu.be/xyz", "video"),
        ("https://forms.gle/x", "link"),
        ("https://drive.google.com/drive/folders/x", "link"),
        ("https://drive.google.com/open?id=CCC", "drive"),
        ("https://drive.google.com/file/d/DDD/view", "drive"),
        ("https://example.edu/notes/lec1.pdf", "file"),
        ("https://example.edu/code/fib.scm", "file"),
        ("https://example.edu/lab/lab00/", "page"),
        ("mailto:staff@example.edu", "link"),
    ],
)
def test_classify(url, kind):
    assert classify(url)[0] == kind


def test_unwrap_and_archived():
    assert unwrap("https://web.archive.org/web/20200123052423/http://inst.eecs.berkeley.edu/~cs61a/su19/") == (
        "20200123052423",
        "http://inst.eecs.berkeley.edu/~cs61a/su19/",
    )
    assert unwrap(SITE) == (None, SITE)
    assert archived("2019", SITE) == f"https://web.archive.org/web/2019id_/{SITE}"


def test_fetch_writes_files_and_manifest(tmp_path, capsys):
    web = FakeWeb(site_pages())
    title = WebsiteProvider().fetch(CoursePlugin(), SITE, tmp_path / "c", web=web)
    assert title == "CS 61A Summer 2019"

    data = json.loads((tmp_path / "c" / "lectures.json").read_text())
    assert data["provider"] == "website" and data["source"] == SITE
    intro, functions = data["lectures"]  # the row with no links isn't a lecture
    assert (intro["number"], intro["title"], intro["date"]) == (1, "Intro", "Mon 6/24")
    assert intro["files"] == ["files/lecture-01/01 - Intro.pdf", "files/lecture-01/01.py"]
    assert {link["text"]: link["kind"] for link in intro["links"]} == {
        "slides": "slides",
        "Video": "video",
        "01.py": "file",
    }
    # The deleted Google Slides deck is reported and skipped; only the Lecture column is used by default.
    assert functions["files"] == ["files/lecture-02/02.py"]
    assert "couldn't fetch https://docs.google.com/presentation/d/GONE/edit" in capsys.readouterr().err
    assert not any("composingprograms" in u or "disc00" in u for u in web.requests)

    # A second fetch reuses the downloaded files.
    web.requests.clear()
    WebsiteProvider().fetch(CoursePlugin(), SITE, tmp_path / "c", web=web)
    assert web.requests == [SITE, "https://docs.google.com/presentation/d/GONE/export/pdf"]


def test_fetch_more_columns(tmp_path):
    pages = site_pages() | {
        "http://composingprograms.com/pages/11-getting-started.html": Response(
            "x", b"<html><body><h1>1.1 Getting Started</h1><p>Hello.</p></body></html>", "text/html", None
        ),
        SITE + "disc/disc00.pdf": pdf_bytes("Discussion 0"),
    }
    plugin = CoursePlugin()
    plugin.site_columns = ("lecture", "textbook", "discussion")
    WebsiteProvider().fetch(plugin, SITE, tmp_path / "c", web=FakeWeb(pages))
    functions = json.loads((tmp_path / "c" / "lectures.json").read_text())["lectures"][1]
    assert functions["files"] == [
        "files/lecture-02/02.py",
        "files/lecture-02/11-getting-started.html",
        "files/lecture-02/disc00.pdf",
    ]


def test_fetch_from_wayback(tmp_path):
    web = FakeWeb(site_pages(prefix="https://web.archive.org/web/2019id_/"))
    WebsiteProvider().fetch(CoursePlugin(), SITE, tmp_path / "c", wayback="2019", web=web)
    assert web.requests[0] == "https://web.archive.org/web/2019id_/" + SITE
    data = json.loads((tmp_path / "c" / "lectures.json").read_text())
    assert data["source"] == "https://web.archive.org/web/2019/" + SITE
    assert len(data["lectures"][0]["files"]) == 2


def test_fetch_login_redirect_suggests_wayback(tmp_path):
    login = Response("https://auth.berkeley.edu/cas/login?service=x", b"<html>Log in</html>", "text/html", None)
    with pytest.raises(SystemExit, match="add --wayback"):
        WebsiteProvider().fetch(CoursePlugin(), SITE, tmp_path / "c", web=FakeWeb({SITE: login}))


def test_materials_from_fetched_course(tmp_path, monkeypatch):
    WebsiteProvider().fetch(CoursePlugin(), SITE, tmp_path / "c", web=FakeWeb(site_pages()))
    out = tmp_path / "out"
    cli.main(["materials", "--input", str(tmp_path / "c"), "--out", str(out)])
    course = json.loads((out / "course.json").read_text())
    assert course["title"] == "CS 61A Summer 2019"
    intro = course["lectures"][0]
    assert (intro["title"], intro["date"]) == ("Intro", "Mon 6/24")
    assert {"text": "Video", "url": "https://youtu.be/xyz", "kind": "video"} in intro["links"]
    md = (out / "materials" / "lecture-01.md").read_text()
    assert "## [1] Welcome to 61A" in md and "## [2] Example code: 01.py" in md


def test_detect_order(tmp_path, ocw_dir, course_dir):
    (tmp_path / "fetched").mkdir()
    (tmp_path / "fetched" / "lectures.json").write_text('{"lectures": []}')
    assert providers.detect(SITE).name == "website"
    assert providers.detect(tmp_path / "fetched").name == "manifest"
    assert providers.detect(ocw_dir).name == "ocw"
    assert providers.detect(course_dir).name == "folder"


def test_custom_provider_from_file(tmp_path, monkeypatch):
    (tmp_path / "my_provider.py").write_text(
        "from coursesitetolectures import Lecture, Provider\n\n"
        "class OneFile(Provider):\n"
        "    name = 'onefile'\n"
        "    def lectures(self, plugin, input_dir, exclude=()):\n"
        "        return [Lecture(1, [p.relative_to(input_dir)], 'Everything') for p in input_dir.glob('*.md')]\n"
    )
    course = tmp_path / "course"
    course.mkdir()
    (course / "notes.md").write_text("# Notes\n\nHello.\n")
    monkeypatch.chdir(tmp_path)
    cli.main(["materials", "--provider", "my_provider.py", "--input", "course"])
    assert json.loads(Path("out/course.json").read_text())["lectures"][0]["title"] == "Everything"


def test_local_provider_cannot_fetch(course_dir):
    with pytest.raises(SystemExit, match="reads local directories"):
        cli.main(["fetch", SITE, "--provider", "folder"])


def test_course_slug():
    assert cli.course_slug(SITE) == "cs61a-su19"
    assert cli.course_slug("https://web.archive.org/web/2019/https://example.edu/") == "example.edu"


def test_provider_base_is_importable():
    assert issubclass(WebsiteProvider, Provider)


def test_drive_link_tries_slides_docs_then_file(tmp_path):
    assert classify("https://drive.google.com/open?id=CCC")[1][0].endswith("/presentation/d/CCC/export/pdf")
    page = SCHEDULE.replace(
        "https://docs.google.com/presentation/d/AAA/edit?usp=sharing", "https://drive.google.com/open?id=CCC"
    )
    pages = site_pages() | {
        SITE: Response(SITE, page.encode(), "text/html", None),
        # Slides export answers with an HTML error page; the Docs export works.
        "https://docs.google.com/presentation/d/CCC/export/pdf": Response("x", b"<html>", "text/html", None),
        "https://docs.google.com/document/d/CCC/export?format=pdf": Response(
            "x", pdf_bytes("Notes"), "application/pdf", "Intro notes.pdf"
        ),
    }
    WebsiteProvider().fetch(CoursePlugin(), SITE, tmp_path / "c", web=FakeWeb(pages))
    intro = json.loads((tmp_path / "c" / "lectures.json").read_text())["lectures"][0]
    assert intro["files"][0] == "files/lecture-01/Intro notes.pdf"


def test_cell_title_keeps_parentheses():
    cell = BeautifulSoup('<td>Special Topics I (Security) <a href="x">slides</a> ( )</td>', "html.parser").td
    assert cell_title(cell) == "Special Topics I (Security)"
