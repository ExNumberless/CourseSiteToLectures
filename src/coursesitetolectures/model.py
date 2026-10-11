from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Lecture:
    number: int | None
    files: list[Path] = field(default_factory=list)  # relative to the course directory
    title: str = ""  # from the provider when it knows one; CoursePlugin.lecture_title decides
    name: str = ""  # stem for output files, from CoursePlugin.output_name
    links: list[dict] = field(default_factory=list)  # {"text", "url", "kind"}, such as the lecture video
    date: str | None = None
    sections: list = field(default_factory=list)  # [(N, Section)]
