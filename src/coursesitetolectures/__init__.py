"""Turn a folder of course materials into lecture transcripts and narrated audio."""

from importlib.metadata import version

from .extract import Section
from .model import Lecture
from .plugin import CoursePlugin
from .providers import Provider
from .report import PrintReporter, Reporter

__version__ = version("coursesitetolectures")
__all__ = ["CoursePlugin", "Lecture", "PrintReporter", "Provider", "Reporter", "Section", "__version__"]
