"""Scrape a course website's schedule table, live or from the Wayback Machine.

Finds the first table with a column whose header matches the plugin's first site_columns pattern
("lecture" by default), and makes a lecture of each row with links in that column. Each lecture
gets the documents linked from the row's site_columns: PDFs, slides, notebooks, code and pages,
with Google Slides and Docs downloaded as PDF. Videos and other links are recorded in
lectures.json, not downloaded.

A URL like https://web.archive.org/web/2019/https://inst.eecs.berkeley.edu/~cs61a/su19/ (or
--wayback 2019) reads the course from the Wayback Machine: its own pages and files come from the
capture nearest that time, and other sites are tried live first, then in the archive. Re-running
fetch reuses files already downloaded unless force is set.

validate_url (see urlcheck) is called on every URL before it's requested, including redirects.
Links it refuses are reported and skipped like other failed downloads; if it refuses the course
page itself, fetch raises BlockedURL.
"""

import re
import sys
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from ..extract import CODE_EXTS, DOC_EXTS, short
from ..model import Lecture
from . import gslides, manifest
from .manifest import ManifestProvider
from .urlcheck import BlockedURL
from .web import Wayback, Web, archived, nearest, unwrap, url_key

GOOGLE = re.compile(r"^/(presentation|document)/d/([\w-]+)")
DRIVE_FILE = re.compile(r"^/file/d/([\w-]+)")
VIDEO_HOSTS = ("youtube.com", "youtu.be", "vimeo.com", "kaltura.com", "panopto.com")
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v"}
SKIP_HOSTS = ("forms.gle", "piazza.com", "gradescope.com", "edstem.org", "okpy.org")
LOGIN = re.compile(r"login|/cas/|auth\.|sso\.|shibboleth", re.IGNORECASE)


def table_grid(table):
    """The table's rows as lists of cells, with each rowspan/colspan cell repeated where it spans."""
    grid, spans = [], {}  # spans: column -> [cell, rows left]
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue
        cells, row, col = tr.find_all(["td", "th"], recursive=False), [], 0
        while cells or col in spans:
            if col in spans:
                cell, left = spans[col]
                row.append(cell)
                if left == 1:
                    del spans[col]
                else:
                    spans[col][1] -= 1
                col += 1
                continue
            cell = cells.pop(0)
            rowspan, colspan = (int(re.sub(r"\D", "", cell.get(a, "1")) or 1) for a in ("rowspan", "colspan"))
            for _ in range(colspan):
                row.append(cell)
                if rowspan > 1:
                    spans[col] = [cell, rowspan - 1]
                col += 1
        grid.append(row)
    return grid


def text(cell):
    return " ".join(cell.get_text(" ").split())


def cell_title(cell):
    """A cell's own text, without the text of its links ("Functions slides Video 02.py" -> "Functions")."""
    words = " ".join(s for s in cell.find_all(string=True) if s.find_parent("a") is None)
    title = re.sub(r"\(\s*\)|\[\s*\]", "", " ".join(words.split())).strip(" |,;:-–")
    if not title and (a := cell.find("a")):
        title = text(a)
    return short(title) if title else None


def find_schedule(soup, columns):
    """(grid, header row index, {column index: header}) for the first table with a lecture column."""
    patterns = [re.compile(p, re.IGNORECASE) for p in columns]
    for table in soup.find_all("table"):
        grid = table_grid(table)
        for i, row in enumerate(grid[:5]):
            headers = [text(c) for c in row]
            if any(patterns[0].search(h) for h in headers):
                return grid, i, {j: h for j, h in enumerate(headers) if any(p.search(h) for p in patterns)}
    return None


def google_exports(doc_id):
    """Download URLs to try for a Google Drive ID of unknown type: Slides, Docs, then an uploaded file."""
    return [
        f"https://docs.google.com/presentation/d/{doc_id}/export/pdf",
        f"https://docs.google.com/document/d/{doc_id}/export?format=pdf",
        f"https://drive.google.com/uc?export=download&id={doc_id}",
    ]


def classify(url):
    """(kind, [download URLs to try]) for a link: slides, document, drive, file, page, video or link."""
    parts = urlsplit(url)
    host, suffix = parts.netloc.lower(), Path(unquote(parts.path)).suffix.lower()
    if host == "docs.google.com" and (m := GOOGLE.match(parts.path)):
        kind, doc_id = m.groups()
        if kind == "presentation":
            return "slides", [f"https://docs.google.com/presentation/d/{doc_id}/export/pdf"]
        return "document", [f"https://docs.google.com/document/d/{doc_id}/export?format=pdf"]
    if host == "drive.google.com":
        if m := DRIVE_FILE.match(parts.path):
            return "drive", google_exports(m.group(1))[2:]
        if doc_id := parse_qs(parts.query).get("id", [None])[0]:
            return "drive", google_exports(doc_id)
        return "link", []  # a folder
    if any(h in host for h in VIDEO_HOSTS) or suffix in VIDEO_EXTS:
        return "video", []
    if parts.scheme not in ("http", "https") or any(h in host for h in SKIP_HOSTS):
        return "link", []
    if suffix in (DOC_EXTS | CODE_EXTS) - {".html", ".htm"}:
        return "file", [url]
    if suffix in ("", ".html", ".htm"):
        return "page", [url]
    return "link", []


def file_name(response, url, kind):
    name = response.filename or unquote(Path(urlsplit(url).path).name) or "index.html"
    name = re.sub(r'[/\\:*?"<>|]+', "_", name).strip() or "file"
    if kind == "page" and Path(name).suffix.lower() not in (".html", ".htm"):
        name += ".html"
    if kind in ("slides", "document") and not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name


def google_id(url):
    """The document ID in a Google Slides, Docs or Drive link, or None."""
    parts = urlsplit(url)
    if parts.netloc.lower() == "docs.google.com" and (m := GOOGLE.match(parts.path)):
        return m.group(2)
    if parts.netloc.lower() == "drive.google.com":
        if m := DRIVE_FILE.match(parts.path):
            return m.group(1)
        return parse_qs(parts.query).get("id", [None])[0]
    return None


class Fetcher:
    """Downloads for one course: its own files from the Wayback Machine when reading an archived
    copy (at the capture nearest the timestamp, per the CDX index), other sites live first."""

    def __init__(self, web, page_url, timestamp):
        self.web, self.timestamp = web, timestamp
        self.site = urlsplit(page_url).netloc.lower()
        self.wayback = Wayback(web)
        self.index = None
        if timestamp:
            self.index = self.wayback.index(page_url.rsplit("/", 1)[0] + "/")
            if self.index is None:
                print("  the Wayback Machine's index is unavailable; trying each file", file=sys.stderr)

    def archived(self, link):
        if self.index is None:
            return self.web.get(archived(self.timestamp, link))
        captures = self.index.get(url_key(link))
        if not captures:
            raise urllib.error.URLError("not in the Wayback Machine")
        when, original = nearest(captures, self.timestamp)[0]
        return self.web.get(archived(when, original))

    def get(self, link):
        if self.timestamp and urlsplit(link).netloc.lower() == self.site:
            return self.archived(link)
        try:
            response = self.web.get(link)
        except urllib.error.URLError:
            if not self.timestamp:
                raise
            return self.web.get(archived(self.timestamp, link))
        if LOGIN.search(response.url) and urlsplit(response.url).netloc.lower() != urlsplit(link).netloc.lower():
            raise urllib.error.URLError(f"redirected to a login page: {response.url}")
        return response

    def download(self, url, kind, candidates):
        """(content, file name) for a link, or raise URLError with the reason it couldn't be fetched."""
        problem = None
        for candidate in candidates:
            try:
                response = self.get(candidate)
            except urllib.error.URLError as e:
                problem = getattr(e, "reason", e)
                continue
            if kind == "page" or response.content_type != "text/html":
                return response.content, file_name(response, candidate, kind)
            problem = "a web page, not a file"
        if kind in ("slides", "drive") and (doc_id := google_id(url)) and (found := self.archived_slides(doc_id)):
            return found
        raise urllib.error.URLError(problem)

    def archived_slides(self, doc_id):
        """(content, file name) for a deleted Google Slides deck from the Wayback Machine, or None:
        an archived PDF export if there is one, else the text rebuilt from an archived editor page."""
        captures = self.wayback.captures(f"docs.google.com/presentation/d/{doc_id}", prefix=True) or []
        pdfs = [c for c in captures if c[2] == "application/pdf"]
        for when, original, _ in nearest(pdfs, self.timestamp)[:2]:
            try:
                response = self.web.get(archived(when, original))
                return response.content, file_name(response, original, "slides")
            except urllib.error.URLError:
                continue
        pages = [c for c in captures if c[2] == "text/html" and re.search(r"/(edit|present|pub)\b", c[1])]
        for when, original, _ in nearest(pages, self.timestamp)[:3]:
            try:
                html = self.web.get(archived(when, original)).content.decode(errors="replace")
            except urllib.error.URLError:
                continue
            if parsed := gslides.parse(html):
                title, slides = parsed
                name = re.sub(r'[/\\:*?"<>|]+', "_", title).strip() or doc_id
                print(f"  rebuilt {len(slides)} slides of {title!r} from the Wayback Machine ({when[:8]})")
                return gslides.markdown(slides).encode(), f"{name}.md"
        return None


class WebsiteProvider(ManifestProvider):
    name = "website"
    online = True

    def detect(self, source):
        return isinstance(source, str) and source.startswith(("http://", "https://"))

    def fetch(self, plugin, url, dest, wayback=None, force=False, web=None, validate_url=None):
        """validate_url is passed to the Web client created when web isn't given."""
        timestamp, page_url = unwrap(url)
        web = web or Web(delay=plugin.fetch_delay, validate_url=validate_url)
        fetcher = Fetcher(web, page_url, timestamp or wayback)
        try:
            page = fetcher.get(page_url)
        except BlockedURL:
            raise
        except urllib.error.URLError as e:
            hint = "" if fetcher.timestamp else " (for an archived copy, add --wayback with a year such as 2019)"
            raise SystemExit(f"couldn't fetch {page_url}: {getattr(e, 'reason', e)}{hint}") from None
        soup = BeautifulSoup(page.content, "html.parser")
        title = " ".join(soup.title.get_text().split()) if soup.title else page_url
        found = find_schedule(soup, plugin.site_columns)
        if not found:
            raise SystemExit(f"no schedule table with a column matching {plugin.site_columns[0]!r} on {page_url}")

        dest.mkdir(parents=True, exist_ok=True)
        previous = {}  # url -> file from an earlier fetch
        if not force and (dest / manifest.NAME).exists():
            for item in manifest.read(dest)["lectures"]:
                for link in item.get("links", []):
                    if link.get("file") and (dest / link["file"]).exists():
                        previous[link["url"]] = link["file"]

        lectures = schedule_lectures(page_url, *found)
        for lecture in lectures:
            folder = Path("files") / f"lecture-{lecture.number:02d}"
            for link in lecture.links:
                kind, candidates = classify(link["url"])
                link["kind"] = kind
                if not candidates:
                    continue
                if link["url"] not in previous:
                    try:
                        content, name = fetcher.download(link["url"], kind, candidates)
                    except urllib.error.URLError as e:
                        print(f"  {lecture.title}: couldn't fetch {link['url']}: {e.reason}", file=sys.stderr)
                        continue
                    path, n = folder / name, 2
                    while path in lecture.files:
                        path, n = (folder / name).with_stem(f"{Path(name).stem}-{n}"), n + 1
                    (dest / path).parent.mkdir(parents=True, exist_ok=True)
                    (dest / path).write_bytes(content)
                    previous[link["url"]] = path.as_posix()
                    print(f"  {path}")
                link["file"] = previous[link["url"]]
                lecture.files.append(Path(link["file"]))
            print(f"{lecture.number}. {lecture.title}: {len(lecture.files)} file(s), {len(lecture.links)} link(s)")

        source = url if not wayback or timestamp else archived(wayback, page_url).replace("id_/", "/")
        manifest.write(dest, self.name, title, source, lectures)
        return title


def schedule_lectures(page_url, grid, header, columns):
    """A Lecture, with its links but no files yet, for each schedule row with links in the lecture column."""
    title_col = min(columns)
    date_col = next(
        (j for j, h in enumerate(text(c) for c in grid[header]) if re.search(r"\bdate\b", h, re.IGNORECASE)), None
    )
    lectures, seen = [], set()
    for row in grid[header + 1 :]:
        if len(row) <= title_col or id(row[title_col]) in seen:
            continue
        seen.add(id(row[title_col]))
        if not row[title_col].find("a", href=True):
            continue  # no lecture this day
        lecture = Lecture(len(lectures) + 1, title=cell_title(row[title_col]) or "")
        if date_col is not None and date_col < len(row):
            lecture.date = text(row[date_col]) or None
        for j in sorted(columns):
            for a in row[j].find_all("a", href=True) if j < len(row) else []:
                link = urljoin(page_url, a["href"].strip())
                if all(link != existing["url"] for existing in lecture.links):
                    lecture.links.append({"text": text(a), "url": link})
        lectures.append(lecture)
    return lectures
