"""Lectures from an MIT OpenCourseWare course export, using the export's own metadata.

An export has a data.json describing the course, resources/<id>/data.json describing each file
(its type, such as "Lecture Notes", the page it belongs to, and its file in static_resources/), and
pages/<name>/data.json with each page's HTML. Every table row or list item on a page that links to
resources of the chosen types becomes one lecture, in page order, titled from the row's text.
Resources that no row or list item links to (such as a single PDF of the whole set of notes) are
skipped, or each becomes a lecture of its own with unnumbered = "separate".
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup

from ..extract import short
from ..model import Lecture
from . import Provider

RESOURCE_LINK = re.compile(r"resources/([^/#?]+)/")
FILE_NOTE = re.compile(r"\(\s*(?:PDF|ZIP|PY|TXT|MP4|HTML)\b[^)]*\)", re.IGNORECASE)


def is_export(input_dir):
    try:
        data = json.loads((input_dir / "data.json").read_text())
    except (OSError, ValueError):
        return False
    return "site_short_id" in data and (input_dir / "resources").is_dir()


def course_title(input_dir):
    """The course number and title, e.g. "18.014 Calculus with Theory"."""
    data = json.loads((input_dir / "data.json").read_text())
    return " ".join(filter(None, [data.get("primary_course_number"), data.get("course_title")])) or None


def resources(input_dir):
    """{resource id: metadata} for every file resource in the export."""
    found = {}
    for meta_path in sorted((input_dir / "resources").glob("*/data.json")):
        meta = json.loads(meta_path.read_text())
        if meta.get("file"):
            path = input_dir / "static_resources" / Path(meta["file"]).name
            if path.exists():
                found[meta_path.parent.name] = meta | {"path": path.relative_to(input_dir)}
    return found


def pages(input_dir):
    """[(uid, HTML)] for every page, in path order."""
    out = []
    for meta_path in sorted((input_dir / "pages").glob("*/data.json")):
        meta = json.loads(meta_path.read_text())
        out.append((meta.get("uid"), meta.get("content") or ""))
    return out


def row_title(element, rows):
    """The text of a table row or list item, as a title, without "(PDF)" notes."""
    if element.name == "tr":
        cells = [" ".join(c.get_text(" ").split()) for c in element.find_all(["td", "th"])]
        text = ": ".join(FILE_NOTE.sub("", c).strip() for c in cells if FILE_NOTE.sub("", c).strip())
    else:
        text = FILE_NOTE.sub("", element.get_text(" "))
    return short(text.strip(" :-–")) or f"Lecture {len(rows) + 1}"


def listed_groups(html, wanted):
    """[(title, [resource id])] for each table row or list item linking to wanted resources."""
    rows = []
    for element in BeautifulSoup(html, "html.parser").find_all(["tr", "li"]):
        if element.find(["tr", "li"]):
            continue  # only the innermost rows and items
        ids = []
        for a in element.find_all("a", href=True):
            if (m := RESOURCE_LINK.search(a["href"])) and m.group(1) in wanted and m.group(1) not in ids:
                ids.append(m.group(1))
        if ids:
            rows.append((row_title(element, rows), ids))
    return rows


def groups(plugin, input_dir):
    """[(title, [file path relative to input_dir])] for the export's lectures, in order."""
    all_resources = resources(input_dir)
    wanted = {
        rid: meta
        for rid, meta in all_resources.items()
        if set(meta.get("learning_resource_types") or []) & set(plugin.ocw_types) and plugin.include(meta["path"])
    }
    if not wanted:
        types = Counter(t for meta in all_resources.values() for t in meta.get("learning_resource_types") or [])
        available = ", ".join(f"{t!r} ({n})" for t, n in types.most_common())
        raise SystemExit(
            f"no resources of type {', '.join(map(repr, plugin.ocw_types))}; ocw_types can be: {available}"
        )

    # A resource's lecture comes from its own parent page when that page lists it, else from any page.
    by_page = {uid: listed_groups(html, wanted) for uid, html in pages(input_dir)}
    ordered = sorted(by_page, key=lambda uid: uid not in {meta.get("parent_uid") for meta in wanted.values()})
    groups, placed = [], set()
    for uid in ordered:
        for title, ids in by_page[uid]:
            ids = [rid for rid in ids if rid not in placed]
            if ids:
                placed.update(ids)
                groups.append((title, [wanted[rid]["path"] for rid in ids]))

    unlisted = [meta["path"] for rid, meta in wanted.items() if rid not in placed]
    if plugin.unnumbered == "separate":
        groups += [(None, [path]) for path in unlisted]
    elif unlisted:
        names = ", ".join(p.name for p in unlisted)
        print(f"{len(unlisted)} file(s) not listed on any page skipped: {names}", file=sys.stderr)
    return groups


class OCWProvider(Provider):
    name = "ocw"

    def detect(self, source):
        return isinstance(source, Path) and is_export(source)

    def course_title(self, input_dir):
        return course_title(input_dir)

    def lectures(self, plugin, input_dir, exclude=()):
        return [
            Lecture(i if title is not None else None, files, title or "")
            for i, (title, files) in enumerate(groups(plugin, input_dir), 1)
        ]
