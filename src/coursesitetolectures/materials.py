"""Group course files into lectures and write each lecture's materials as Markdown.

Each lecture's file has one "## [N] Title" section per page, slide, heading or code file, numbered
across the whole course: the format SlidesToLectures' lecture step reads. course.json records, for
every section number, the file and page or slide it came from. Lecture audio has a chapter per
section titled "[N] Title", so a player can show the matching page while the audio plays.
"""

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from slidestolectures.paths import rel as display

from .extract import extract


@dataclass
class Lecture:
    number: int | None
    files: list[Path] = field(default_factory=list)  # relative to the course directory
    title: str = ""
    name: str = ""  # stem for output files, from CoursePlugin.output_name
    sections: list = field(default_factory=list)  # [(N, Section)]


def find_lectures(plugin, input_dir, exclude=()):
    """The course's lectures in order: numbered ones by number, then unnumbered documents."""
    exclude = [p.resolve() for p in exclude]
    numbered, unnumbered, skipped = {}, [], []
    for path in sorted(input_dir.rglob("*")):
        rel = path.relative_to(input_dir)
        if not path.is_file() or not plugin.include(rel) or any(path.resolve().is_relative_to(e) for e in exclude):
            continue
        number = plugin.lecture_number(rel)
        if number is not None:
            numbered.setdefault(number, Lecture(number)).files.append(rel)
        elif plugin.unnumbered == "separate":
            unnumbered.append(Lecture(None, [rel]))
        else:
            skipped.append(rel)
    if skipped:
        print(
            f'{len(skipped)} file(s) with no lecture number skipped (set unnumbered = "separate" to include them)',
            file=sys.stderr,
        )
    lectures = [numbered[n] for n in sorted(numbered)] + unnumbered
    for lecture in lectures:
        lecture.files = plugin.order_files(lecture.files)
        lecture.title = plugin.lecture_title(lecture.number, lecture.files)
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
        parts.append(f"## [{n}] {s.title}" + (f"\n\n{s.body}" if s.body else ""))
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
                "sections": [
                    {"n": n, "title": s.title, "source": s.source, "locator": s.locator} for n, s in lec.sections
                ],
            }
            for lec in lectures
        ],
    }


def run(cfg, names=(), dry_run=False):
    """Write <materials dir>/<name>.md for the chosen lectures, and course.json for the whole course."""
    lectures = find_lectures(cfg.plugin, cfg.input, exclude=[cfg.output])
    load(cfg.plugin, lectures, cfg.input)
    chosen = select(lectures, names)
    if dry_run:
        for lec in chosen:
            first, last = (lec.sections[0][0], lec.sections[-1][0]) if lec.sections else (0, 0)
            print(f"{lec.name}: {lec.title} [{first}-{last}]")
            for f in lec.files:
                print(f"    {f}")
        return

    cfg.materials.mkdir(parents=True, exist_ok=True)
    for lec in chosen:
        out = cfg.materials / f"{lec.name}.md"
        out.write_text(markdown(lec))
        print(f"{len(lec.files)} file(s), {len(lec.sections)} sections -> {display(out)}")
    course = cfg.output / "course.json"
    course.write_text(json.dumps(index(lectures, cfg), indent=2) + "\n")
    print(f"-> {display(course)}")
