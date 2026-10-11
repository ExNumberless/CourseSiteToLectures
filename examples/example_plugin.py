"""An example CourseSiteToLectures plugin for an MIT OpenCourseWare download.

Use it with `course-site-to-lectures materials --input 6.006 --plugin examples/example_plugin.py`,
or name it in coursesitetolectures.toml:

    plugin = "example_plugin.py"
    input = "6.006"
"""

from coursesitetolectures import CoursePlugin

TITLES = {
    1: "Algorithmic Thinking, Peak Finding",
    2: "Models of Computation, Document Distance",
    3: "Insertion Sort, Merge Sort",
}


class OCWPlugin(CoursePlugin):
    # Context for the lecture prompt.
    course = "MIT 6.006 Introduction to Algorithms"
    audience = "undergraduates who know some Python"
    relevance = "for designing and analyzing efficient programs"

    def include(self, rel):
        # Only the lecture notes and example code; skip recitations, problem sets and site pages.
        return super().include(rel) and rel.suffix.lower() in {".pdf", ".py"} and "_r" not in rel.stem

    def lecture_title(self, number, files, detected):
        if number in TITLES:
            return f"Lecture {number}: {TITLES[number]}"
        return super().lecture_title(number, files, detected)
