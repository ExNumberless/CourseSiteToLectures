"""An example materials provider: a course website whose lectures are a list of links, not a table.

Use it with `course-site-to-lectures fetch URL --provider examples/example_provider.py`, then
`materials --input <the fetched directory>` (lectures.json remembers the course; the built-in
manifest provider reads it). To publish a provider in a package, register it as an entry point:

    [project.entry-points."coursesitetolectures.providers"]
    listsite = "my_package.providers:ListSiteProvider"
"""

import re
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from coursesitetolectures import Lecture
from coursesitetolectures.providers import manifest
from coursesitetolectures.providers.manifest import ManifestProvider
from coursesitetolectures.providers.web import Web


class ListSiteProvider(ManifestProvider):
    """Each <li> under the "Lectures" heading is a lecture; its PDF links are the materials."""

    name = "listsite"
    online = True

    def detect(self, source):
        return False  # only when named with --provider or provider = ...

    def fetch(self, plugin, url, dest, wayback=None, force=False, web=None):
        web = web or Web(delay=plugin.fetch_delay)
        soup = BeautifulSoup(web.get(url).content, "html.parser")
        heading = soup.find(re.compile("^h[1-6]$"), string=re.compile("lectures", re.IGNORECASE))
        lectures = []
        for i, item in enumerate(heading.find_next("ul").find_all("li"), 1):
            lecture = Lecture(i, title=" ".join(item.get_text(" ").split()))
            for a in item.find_all("a", href=re.compile(r"\.pdf$", re.IGNORECASE)):
                link = urljoin(url, a["href"])
                path = Path("files") / f"lecture-{i:02d}" / Path(link).name
                if force or not (dest / path).exists():
                    (dest / path).parent.mkdir(parents=True, exist_ok=True)
                    (dest / path).write_bytes(web.get(link).content)
                lecture.files.append(path)
                lecture.links.append({"text": a.get_text(strip=True), "url": link, "kind": "file", "file": str(path)})
            lectures.append(lecture)
        title = soup.title.get_text(strip=True) if soup.title else url
        manifest.write(dest, self.name, title, url, lectures)
        return title
