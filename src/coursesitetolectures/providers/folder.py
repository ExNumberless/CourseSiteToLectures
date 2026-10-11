"""Any directory of course files, grouped by the lecture number in each file's name or folder."""

import sys
from pathlib import Path

from ..model import Lecture
from . import Provider


class FolderProvider(Provider):
    name = "folder"

    def detect(self, source):
        return isinstance(source, Path) and source.is_dir()

    def lectures(self, plugin, input_dir, exclude=()):
        exclude = [p.resolve() for p in exclude]
        numbered, unnumbered, skipped = {}, [], []
        for path in sorted(input_dir.rglob("*")):
            rel = path.relative_to(input_dir)
            if not path.is_file() or not plugin.include(rel):
                continue
            if any(path.resolve().is_relative_to(e) for e in exclude):
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
        return [numbered[n] for n in sorted(numbered)] + unnumbered
