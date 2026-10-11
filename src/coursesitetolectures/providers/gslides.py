"""Rebuild a Google Slides deck's text from a saved copy of its editor page.

When a deck is deleted or made private, its PDF export is gone, but the Wayback Machine often has
captures of its /edit page. That page embeds the deck's document model as JSON operations
(DOCS_modelChunk): [12, page id, index, ...] inserts a page, [3, shape id, kind, transform, ...,
page id] puts a shape on a page, and [15, shape id, null, index, text] inserts text into a shape.
Slides are the pages that have a "<id>:notes" speaker notes page.
"""

import json
import re
from html import unescape

CHUNK = re.compile(r"DOCS_modelChunk = (\[.*?\]);\s*DOCS_modelChunkLoadStart", re.DOTALL)
TITLE = re.compile(r"<title>(.*?)(?: - Google (?:Slides|Docs|Drive))?</title>", re.DOTALL)


def operations(html):
    ops = []
    for chunk in CHUNK.findall(html):
        try:
            ops += json.loads(chunk)
        except ValueError:
            continue
    return [op for op in ops if isinstance(op, list) and op]


def parse(html):
    """(deck title, [(slide title, body, speaker notes)]) from an editor page, or None."""
    ops = operations(html)
    page_of, position, text = {}, {}, {}
    for op in ops:
        if op[0] == 3 and len(op) > 5 and isinstance(op[5], str):
            page_of[op[1]] = op[5]
            t = op[3]
            position[op[1]] = (t[5], t[4]) if isinstance(t, list) and len(t) >= 6 else (0, 0)  # top, left
        elif op[0] == 15 and len(op) > 4 and isinstance(op[3], int) and isinstance(op[4], str):
            s = text.get(op[1], "")
            text[op[1]] = s[: op[3]] + op[4] + s[op[3] :]

    has_notes = {page.removesuffix(":notes") for page in page_of.values() if page.endswith(":notes")}
    order = []
    for op in ops:
        if op[0] == 12 and len(op) > 2 and op[1] in has_notes and isinstance(op[2], int):
            if op[1] in order:
                order.remove(op[1])
            order.insert(op[2], op[1])
    if not order:
        return None

    def texts(page):
        shapes = sorted((s for s, p in page_of.items() if p == page and text.get(s, "").strip()), key=position.get)
        return [text[s].strip().replace("\x0b", "\n") for s in shapes]

    slides = []
    for page in order:
        parts = texts(page)
        title = parts[0].splitlines()[0].strip() if parts else ""
        if parts:
            parts[0] = "\n".join(parts[0].splitlines()[1:]).strip()
        body = "\n\n".join(p for p in parts if p)
        slides.append((title, body, "\n\n".join(texts(page + ":notes"))))
    m = TITLE.search(html)
    return (unescape(m.group(1)).strip() if m else ""), slides


def markdown(slides):
    """Markdown with a "## Title" section per slide, which extraction splits into sections.

    Lines in slide text that start with "#" (such as code comments) are escaped so they aren't
    read as headings.
    """
    sections = []
    for i, (title, body, notes) in enumerate(slides, 1):
        content = [body] if body else []
        if notes:
            content.append(f"Speaker notes:\n\n{notes}")
        escaped = re.sub(r"^#", r"\\#", "\n\n".join(content), flags=re.MULTILINE)
        sections.append(f"## {title or f'Slide {i}'}" + (f"\n\n{escaped}" if escaped else ""))
    return "\n\n".join(sections) + "\n"
