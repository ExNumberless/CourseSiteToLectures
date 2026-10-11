"""Slides for the lecture player: one per materials section, from the course materials alone.

render writes <slides dir>/<name>/: a WebP image per PDF page (and per PowerPoint slide, when
LibreOffice is installed to convert the deck to PDF), and slides.json, which lists every slide with
its kind, title, content, and the file and page or slide it came from. Each slide is one of:

- image: a PDF page, scanned or not, or a PowerPoint slide, rendered to <N>.webp
- markdown: everything else with text (rebuilt Google Slides, HTML, Markdown, notebook cells,
  transcribed text), taken from the lecture's materials file
- code: an example code file

The assemble step reads slides.json and writes player.json, adding the lecture audio and each
slide's narration and audio times (narration, start_ms, end_ms) from the lecture transcript and its
audio chapters. slides.schema.json and player.schema.json, next to this module, are their JSON
Schemas; the player schema extends the slides one.
"""

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pymupdf
from PIL import Image
from slidestolectures.paths import rel as display

from .extract import CODE_EXTS

SLIDES_SCHEMA = Path(__file__).with_name("slides.schema.json")
PLAYER_SCHEMA = Path(__file__).with_name("player.schema.json")
VERSION = 1  # slides.json's and player.json's "version"; bump on incompatible changes to the schemas
DPI = 150  # a US letter page renders to 1275 x 1650, a 10-inch slide to 1500 pixels wide
WEBP_QUALITY = 80
SECTION = re.compile(r"^## \[(\d+)\][^\n]*\n?", re.MULTILINE)  # the materials file's section headings
SPEAKER_NOTES = re.compile(r"(?:^|\n\n)Speaker notes:\n.*", re.DOTALL)
PAGE = re.compile(r"^(page|slide) (\d+)$")
# Syntax highlighting names (highlight.js and Prism) where they differ from the file extension.
LANGUAGES = {
    ".py": "python", ".h": "c", ".cc": "cpp", ".hpp": "cpp", ".js": "javascript", ".ts": "typescript",
    ".m": "matlab", ".jl": "julia", ".rs": "rust", ".hs": "haskell", ".ml": "ocaml", ".rkt": "scheme",
    ".scm": "scheme", ".sh": "bash",
}  # fmt: skip


def find_soffice():
    """The LibreOffice command, or None if it isn't installed."""
    app = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    return shutil.which("soffice") or shutil.which("libreoffice") or (str(app) if app.exists() else None)


def pptx_to_pdf(path, out_dir, soffice):
    """Convert a PowerPoint deck to PDF in out_dir with LibreOffice; the PDF's path, or None if it failed."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    # A profile of its own, so conversions for other lectures can run at the same time.
    profile = (Path(out_dir) / "profile").resolve().as_uri()
    cmd = [soffice, f"-env:UserInstallation={profile}", "--headless", "--convert-to", "pdf", "--outdir", out_dir]
    try:
        subprocess.run([*cmd, str(path)], capture_output=True, timeout=300, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    pdf = Path(out_dir) / f"{Path(path).stem}.pdf"
    return pdf if pdf.exists() else None


def write_webp(page, path, dpi=DPI):
    """Render a PDF page to a WebP image at path; its (width, height) in pixels."""
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    image.save(path, "WEBP", quality=WEBP_QUALITY, method=6)
    return pix.width, pix.height


def bodies(materials):
    """{N: section body} from a lecture's materials Markdown."""
    parts = SECTION.split(materials)[1:]  # [N, body, N, body, ...]
    return {int(n): body.strip() for n, body in zip(parts[::2], parts[1::2], strict=True)}


def slide_markdown(body, title):
    """A section body as shown on a slide, under its title: without the speaker notes, which are for
    narration, or a first heading that repeats the title (as notebook cells have)."""
    body = SPEAKER_NOTES.sub("", body).strip()
    first, _, rest = body.partition("\n")
    if re.fullmatch(r"#{1,6} +(.+)", first) and " ".join(first.lstrip("#").split()) == " ".join(title.split()):
        body = rest.strip()
    return body


def render(course, name, out_dir=None, input_dir=None, dpi=DPI, soffice=None):
    """Write the slide images and slides.json for the lecture called name; the slides.json path.

    course is the course.json that the materials step wrote. out_dir defaults to slides/<name> next
    to it, and input_dir (the course materials) to the directory course.json records. soffice is
    the LibreOffice command for converting PowerPoint decks (default: find_soffice()); without it
    their slides are Markdown.

    Reads only course.json, this lecture's materials file and its source files, and writes only
    out_dir, so lectures can be rendered in parallel.
    """
    course = Path(course)
    index = json.loads(course.read_text())
    lecture = next((lec for lec in index["lectures"] if lec["name"] == name), None)
    if lecture is None:
        raise SystemExit(f"{display(course)}: no lecture named {name!r}")
    input_dir = Path(input_dir or index["source"])
    out_dir = Path(out_dir or course.parent / "slides" / name)
    text = bodies((course.parent / lecture["materials"]).read_text())
    soffice = soffice or find_soffice()

    out_dir.mkdir(parents=True, exist_ok=True)
    docs, images = {}, set()
    with tempfile.TemporaryDirectory() as tmp:

        def document(source):
            """The PDF to render source's pages or slides from, or None."""
            if source not in docs:
                path, ext = input_dir / source, Path(source).suffix.lower()
                if ext == ".pptx" and soffice and path.exists():
                    path = pptx_to_pdf(path, Path(tmp) / str(len(docs)), soffice)
                docs[source] = pymupdf.open(path) if path and path.suffix.lower() == ".pdf" and path.exists() else None
            return docs[source]

        def slide(section):
            n, source, locator = section["n"], section["source"], section["locator"]
            base = {"n": n, "kind": "markdown", "title": section["title"], "source": source, "locator": locator}
            ext = Path(source).suffix.lower()
            m = PAGE.match(locator or "")
            if m and (doc := document(source)) is not None and int(m.group(2)) <= doc.page_count:
                image = f"{n}.webp"
                width, height = write_webp(doc[int(m.group(2)) - 1], out_dir / image, dpi)
                images.add(image)
                return {**base, "kind": "image", "image": image, "width": width, "height": height}
            if ext in CODE_EXTS and locator is None and (input_dir / source).exists():
                code = (input_dir / source).read_text(errors="replace").strip()
                return {**base, "kind": "code", "code": code, "language": LANGUAGES.get(ext, ext[1:])}
            return {**base, "markdown": slide_markdown(text.get(n, ""), section["title"])}

        try:
            slides = [slide(s) for s in lecture["sections"]]
        finally:
            for doc in docs.values():
                if doc is not None:
                    doc.close()

    for stale in out_dir.glob("*.webp"):
        if stale.name not in images:
            stale.unlink()
    deck = {
        "version": VERSION,
        "course": index["title"],
        "name": name,
        "title": lecture["title"],
        "number": lecture["number"],
        "slides": slides,
    }
    path = out_dir / "slides.json"
    path.write_text(json.dumps(deck, indent=2, ensure_ascii=False) + "\n")
    kinds = {kind: sum(s["kind"] == kind for s in slides) for kind in ("image", "markdown", "code")}
    print(f"{name}: " + ", ".join(f"{count} {kind}" for kind, count in kinds.items() if count) + f" -> {display(path)}")
    return path


def run(cfg, names=()):
    """Render the chosen lectures' slides (all lectures if names is empty) into cfg.slides."""
    course = cfg.output / "course.json"
    if not course.exists():
        raise SystemExit(f"no {display(course)}: run materials first")
    lectures = json.loads(course.read_text())["lectures"]
    chosen = []
    for want in names:
        matches = [lec["name"] for lec in lectures if want in (lec["name"], str(lec["number"]))]
        if not matches:
            raise SystemExit(f"no lecture named {want!r}")
        chosen += matches
    for name in chosen or [lec["name"] for lec in lectures]:
        render(course, name, cfg.slides / name, cfg.input)
