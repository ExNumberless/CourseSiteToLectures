"""lectures.json: the course an online provider fetched, so later steps work offline.

    {
      "provider": "website",
      "title": "CS 61A Summer 2019",
      "source": "https://web.archive.org/web/2019/https://inst.eecs.berkeley.edu/~cs61a/su19/",
      "fetched": "2026-10-11",
      "lectures": [
        {
          "number": 2,
          "title": "Functions",
          "date": "Tue 6/25",
          "files": ["files/lecture-02/02 - Names and Functions.pdf", "files/lecture-02/02.py"],
          "links": [{"text": "Video", "url": "https://www.youtube.com/watch?v=...", "kind": "video"}]
        }
      ]
    }

File paths are relative to the directory holding lectures.json.
"""

import datetime
import json
import sys
from pathlib import Path

from ..model import Lecture
from . import Provider

NAME = "lectures.json"


def write(dest, provider, title, source, lectures):
    """Write dest/lectures.json for lectures, a list of model.Lecture."""
    data = {
        "provider": provider,
        "title": title,
        "source": source,
        "fetched": datetime.date.today().isoformat(),
        "lectures": [
            {
                "number": lec.number,
                "title": lec.title,
                "date": lec.date,
                "files": [Path(f).as_posix() for f in lec.files],
                "links": lec.links,
            }
            for lec in lectures
        ],
    }
    (dest / NAME).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def read(input_dir):
    return json.loads((input_dir / NAME).read_text())


class ManifestProvider(Provider):
    name = "manifest"

    def detect(self, source):
        return isinstance(source, Path) and (source / NAME).is_file()

    def course_title(self, input_dir):
        return read(input_dir).get("title")

    def lectures(self, plugin, input_dir, exclude=()):
        lectures = []
        for item in read(input_dir)["lectures"]:
            files = [Path(f) for f in item.get("files", []) if (input_dir / f).is_file() and plugin.include(Path(f))]
            if not files:
                print(f"no materials for {item.get('title') or item.get('number')}; skipped", file=sys.stderr)
                continue
            lectures.append(
                Lecture(item.get("number"), files, item.get("title") or "", links=item.get("links", []),
                        date=item.get("date"))
            )  # fmt: skip
        return lectures
