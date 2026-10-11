"""Group course files into lectures and write each lecture's materials as Markdown.

Each lecture's file has one "## [N] Title" section per page, slide, heading or code file, numbered
across the whole course: the format SlidesToLectures' lecture step reads. course.json records, for
every section number, the file and page or slide it came from. Lecture audio has a chapter per
section titled "[N] Title", so a player can show the matching page while the audio plays.
"""

import json
import os

from slidestolectures.paths import rel as display

from . import providers
from .extract import extract
from .report import PrintReporter


def find_lectures(plugin, input_dir, exclude=(), provider=None, reporter=None):
    """The course's lectures in order, from provider (default: the one detected for input_dir).

    The provider's warnings go to reporter (default: its own, which prints).
    """
    provider = provider or providers.detect(input_dir)
    if reporter is not None:
        provider.reporter = reporter
    return finish(plugin, provider.lectures(plugin, input_dir, exclude), input_dir)


def finish(plugin, lectures, input_dir):
    """Order each lecture's files and name it, with the plugin's hooks."""
    for lecture in lectures:
        lecture.files = plugin.order_files(lecture.files)
        lecture.title = plugin.lecture_title(lecture.number, lecture.files, lecture.title or None)
        lecture.name = plugin.output_name(lecture)
    if not lectures:
        raise SystemExit(f"no lecture materials found in {input_dir}")
    return lectures


def load(plugin, lectures, input_dir):
    """Extract every lecture's sections, numbered across the course."""
    n = 1
    for lecture in lectures:
        lecture.sections = []
        for rel in lecture.files:
            for section in extract(input_dir / rel, rel.as_posix()):
                if plugin.keep_section(section):
                    lecture.sections.append((n, section))
                    n += 1


def select(lectures, names):
    """The lectures matching names (output names or numbers), or all lectures if none are given."""
    if not names:
        return lectures
    chosen = []
    for name in names:
        matches = [lec for lec in lectures if name in (lec.name, str(lec.number))]
        if not matches:
            raise SystemExit(f"no lecture named {name!r}")
        chosen += matches
    return chosen


def markdown(lecture):
    parts = [f"# {lecture.title}"]
    for n, s in lecture.sections:
        body = s.body or ("(Scanned page: run materials with --vision to transcribe it.)" if s.scanned else "")
        parts.append(f"## [{n}] {s.title}" + (f"\n\n{body}" if body else ""))
    return "\n\n".join(parts) + "\n"


def index(lectures, cfg):
    """The course.json contents: every lecture, its output files, and where each section came from."""

    def path(p):
        return os.path.relpath(p, cfg.output)

    return {
        "title": cfg.plugin.course or cfg.input.name,
        "source": str(cfg.input.resolve()),
        "lectures": [
            {
                "name": lec.name,
                "title": lec.title,
                "number": lec.number,
                "files": [f.as_posix() for f in lec.files],
                "materials": path(cfg.materials / f"{lec.name}.md"),
                "lecture": path(cfg.lectures / f"{lec.name}.md"),
                "audio": path(cfg.audio / f"{lec.name}.mp3"),
                "date": lec.date,
                "links": lec.links,
                "sections": [
                    {"n": n, "title": s.title, "source": s.source, "locator": s.locator} for n, s in lec.sections
                ],
            }
            for lec in lectures
        ],
    }


def run(cfg, names=(), dry_run=False, vision=False, model=None, reporter=None):
    """Write <materials dir>/<name>.md for the chosen lectures, and course.json for the whole course.

    With vision, scanned pages in the chosen lectures are transcribed with Claude first. Progress,
    messages and Claude usage go to reporter (default: print messages).
    """
    reporter = reporter or PrintReporter()
    lectures = find_lectures(cfg.plugin, cfg.input, [cfg.output], cfg.provider(cfg.input), reporter)
    load(cfg.plugin, lectures, cfg.input)
    chosen = select(lectures, names)
    scanned = [(lec, n, s) for lec in chosen for n, s in lec.sections if s.scanned]
    if dry_run:
        for lec in chosen:
            first, last = (lec.sections[0][0], lec.sections[-1][0]) if lec.sections else (0, 0)
            count = sum(s.scanned for _, s in lec.sections)
            reporter.log(f"{lec.name}: {lec.title} [{first}-{last}]" + (f", {count} scanned pages" if count else ""))
            for f in lec.files:
                reporter.log(f"    {f}")
        if scanned and not vision:
            reporter.log(f"{len(scanned)} scanned pages have no text: add --vision to transcribe them with Claude")
        return
    if scanned and vision:
        from . import vision as vision_step

        vision_step.run(cfg.plugin, scanned, cfg.input, cfg.materials / ".cache", model, reporter)
    elif scanned:
        reporter.log(f"warning: {len(scanned)} scanned pages have no text: add --vision to transcribe them with Claude")

    cfg.materials.mkdir(parents=True, exist_ok=True)
    for i, lec in enumerate(chosen, 1):
        out = cfg.materials / f"{lec.name}.md"
        out.write_text(markdown(lec))
        reporter.log(f"{len(lec.files)} file(s), {len(lec.sections)} sections -> {display(out)}")
        reporter.step("materials", i, len(chosen))
    course = cfg.output / "course.json"
    course.write_text(json.dumps(index(lectures, cfg), indent=2) + "\n")
    reporter.log(f"-> {display(course)}")
