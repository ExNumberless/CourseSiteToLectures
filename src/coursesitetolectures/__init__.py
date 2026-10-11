"""Turn a folder of course materials into lecture transcripts and narrated audio."""

from importlib.metadata import version

from .extract import Section
from .materials import Lecture
from .plugin import CoursePlugin

__version__ = version("coursesitetolectures")
__all__ = ["CoursePlugin", "Lecture", "Section", "__version__"]
