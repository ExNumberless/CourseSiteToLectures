"""Materials providers: each knows one kind of course source and how to find its lectures.

A provider subclasses Provider. Local providers read a directory (lectures); online providers also
download a course from a URL into a directory (fetch), writing lectures.json so that later steps
work offline. Built-in providers:

- website: scrapes a course website's schedule table, live or from the Wayback Machine (online)
- manifest: reads the lectures.json that an online provider's fetch wrote
- ocw: an unzipped MIT OpenCourseWare course export
- folder: any directory, grouping files by the lecture number in their names

Other packages add providers through the "coursesitetolectures.providers" entry point group, and
a config file or --provider can name one as "name", "module:Class" or "path/to/file.py[:Class]".
When none is named, the first provider whose detect() accepts the source is used: entry point
providers first, then the built-ins in the order above.
"""

import importlib
import importlib.util
import sys
from importlib.metadata import entry_points
from pathlib import Path

from ..report import PrintReporter

ENTRY_POINTS = "coursesitetolectures.providers"


class Provider:
    """A kind of course source. Override detect and lectures; online providers also override fetch."""

    name = None
    online = False  # whether fetch downloads courses from URLs
    reporter = PrintReporter()  # where lectures sends warnings (see report.warn); materials sets it

    def detect(self, source):
        """Whether this provider handles source: a Path to a local directory, or a URL string."""
        return False

    def course_title(self, input_dir):
        """The course's title from the source's own metadata, or None."""
        return

    def lectures(self, plugin, input_dir, exclude=()):
        """The course's lectures in order, as model.Lecture objects with files relative to input_dir.

        Leave out files under any path in exclude (the output directory).
        """
        raise NotImplementedError

    def fetch(self, plugin, url, dest, **options):
        """Download the course at url into dest, writing dest/lectures.json (see manifest.write)."""
        raise SystemExit(f"the {self.name} provider can't fetch URLs")


def builtins():
    from .folder import FolderProvider
    from .manifest import ManifestProvider
    from .ocw import OCWProvider
    from .website import WebsiteProvider

    return [WebsiteProvider, ManifestProvider, OCWProvider, FolderProvider]


def registered():
    """{name: Provider class}: entry point providers, then the built-ins."""
    found = {}
    for ep in entry_points(group=ENTRY_POINTS):
        found[ep.name] = ep.load()
    for cls in builtins():
        found.setdefault(cls.name, cls)
    return found


def load(spec, base=None):
    """The provider named by spec: a registered name, "module:Class" or "path/to/file.py[:Class]"."""
    providers = registered()
    if spec in providers:
        return providers[spec]()
    target, _, class_name = spec.partition(":")
    if target.endswith(".py"):
        path = ((base or Path.cwd()) / target).resolve()
        if not path.exists():
            raise SystemExit(f"provider file not found: {path}")
        module_spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[path.stem] = module
        module_spec.loader.exec_module(module)
    else:
        try:
            module = importlib.import_module(target)
        except ImportError:
            raise SystemExit(f"unknown provider {spec!r}; registered: {', '.join(providers)}") from None
    if class_name:
        cls = getattr(module, class_name, None)
    else:
        found = [
            obj
            for obj in vars(module).values()
            if isinstance(obj, type) and issubclass(obj, Provider) and obj.__module__ == module.__name__
        ]
        cls = found[0] if len(found) == 1 else None
    if not (isinstance(cls, type) and issubclass(cls, Provider)):
        raise SystemExit(f"provider {spec!r}: expected one Provider subclass in {module.__name__}")
    return cls()


def detect(source):
    """The first registered provider that handles source (a local Path or a URL string)."""
    for cls in registered().values():
        provider = cls()
        if provider.detect(source):
            return provider
    raise SystemExit(f"no provider handles {source}")


def resolve(spec, source, base=None):
    """The provider named by spec, else the one detected for source."""
    return load(spec, base) if spec else detect(source)
