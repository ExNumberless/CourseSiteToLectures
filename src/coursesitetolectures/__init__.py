"""Turn a folder of course materials into lecture transcripts and narrated audio."""

from importlib.metadata import version

from .extract import Section
from .model import Lecture
from .plugin import CoursePlugin
from .providers import Provider

__version__ = version("coursesitetolectures")
__all__ = ["CoursePlugin", "Lecture", "Provider", "Section", "__version__"]
