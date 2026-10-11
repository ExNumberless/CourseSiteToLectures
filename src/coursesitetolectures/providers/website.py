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
"""

import re
import sys
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from ..extract import CODE_EXTS, DOC_EXTS, short
from ..model import Lecture
from . import manifest
from .manifest import ManifestProvider
from .web import Web, archived, unwrap

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


class WebsiteProvider(ManifestProvider):
    name = "website"
    online = True

    def detect(self, source):
        return isinstance(source, str) and source.startswith(("http://", "https://"))

    def fetch(self, plugin, url, dest, wayback=None, force=False, web=None):
        web = web or Web(delay=plugin.fetch_delay)
        timestamp, page_url = unwrap(url)
        timestamp = timestamp or wayback
        site = urlsplit(page_url).netloc.lower()

        def get(link):
            """Fetch link: the course site's own files from the archive when reading one."""
            same_site = urlsplit(link).netloc.lower() == site
            if timestamp and same_site:
                return web.get(archived(timestamp, link))
            try:
                response = web.get(link)
            except urllib.error.URLError:
                if not timestamp:
                    raise
                return web.get(archived(timestamp, link))
            if LOGIN.search(response.url) and urlsplit(response.url).netloc.lower() != urlsplit(link).netloc.lower():
                raise urllib.error.URLError(f"redirected to a login page: {response.url}")
            return response

        try:
            page = get(page_url)
        except urllib.error.URLError as e:
            hint = "" if timestamp else " (for an archived copy, add --wayback with a year such as 2019)"
            raise SystemExit(f"couldn't fetch {page_url}: {getattr(e, 'reason', e)}{hint}") from None
        soup = BeautifulSoup(page.content, "html.parser")
        title = " ".join(soup.title.get_text().split()) if soup.title else page_url
        found = find_schedule(soup, plugin.site_columns)
        if not found:
            raise SystemExit(f"no schedule table with a column matching {plugin.site_columns[0]!r} on {page_url}")
        grid, header, columns = found
        title_col = min(columns)
        date_col = next(
            (j for j, h in enumerate(text(c) for c in grid[header]) if re.search(r"\bdate\b", h, re.IGNORECASE)), None
        )

        dest.mkdir(parents=True, exist_ok=True)
        previous = {}  # url -> file from an earlier fetch
        if not force and (dest / manifest.NAME).exists():
            for item in manifest.read(dest)["lectures"]:
                for link in item.get("links", []):
                    if link.get("file") and (dest / link["file"]).exists():
                        previous[link["url"]] = link["file"]

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
            folder = Path("files") / f"lecture-{lecture.number:02d}"
            urls = []
            for j in sorted(columns):
                if j < len(row):
                    for a in row[j].find_all("a", href=True):
                        if (link := urljoin(page_url, a["href"].strip())) not in urls:
                            urls.append(link)
                            lecture.links.append({"text": text(a), "url": link})
            for link in lecture.links:
                kind, candidates = classify(link["url"])
                link["kind"] = kind
                if not candidates:
                    continue
                if link["url"] in previous:
                    link["file"] = previous[link["url"]]
                else:
                    response, problem = None, None
                    for download in candidates:
                        try:
                            response = get(download)
                        except urllib.error.URLError as e:
                            problem = getattr(e, "reason", e)
                            continue
                        if kind == "page" or response.content_type != "text/html":
                            break
                        response, problem = None, "a web page, not a file"
                    if response is None:
                        print(f"  {lecture.title}: couldn't fetch {link['url']}: {problem}", file=sys.stderr)
                        continue
                    path = folder / file_name(response, download, kind)
                    taken = {f for f in lecture.files}
                    stem, n = path, 2
                    while path in taken:
                        path, n = stem.with_stem(f"{stem.stem}-{n}"), n + 1
                    (dest / path).parent.mkdir(parents=True, exist_ok=True)
                    (dest / path).write_bytes(response.content)
                    link["file"] = path.as_posix()
                    print(f"  {path}")
                lecture.files.append(Path(link["file"]))
            print(f"{lecture.number}. {lecture.title}: {len(lecture.files)} file(s), {len(lecture.links)} link(s)")
            lectures.append(lecture)

        source = url if not wayback or unwrap(url)[0] else archived(wayback, page_url).replace("id_/", "/")
        manifest.write(dest, self.name, title, source, lectures)
        return title
