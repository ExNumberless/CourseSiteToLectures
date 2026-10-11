"""CoursePlugin: how course materials are grouped into lectures, and the lecture prompts.

It extends slidestolectures.Plugin, so the lecture and tts steps (and settings such as course,
audience, relevance, lecture_model and tts_voice) work the same as in SlidesToLectures. Subclass
it and override what your course needs; call super() to wrap a default.
"""

import re

from slidestolectures import Plugin

from .extract import CODE_EXTS, DOC_EXTS

# "lec01", "Lecture 3", "lecture_12", "session-4", "week2", "L05", but not "tutorial3".
LECTURE_NUMBER = re.compile(
    r"(?<![a-z])(?:lec(?:ture)?|session|week|class|unit|l)[\s_\-]*0*(\d{1,3})(?!\d)", re.IGNORECASE
)
IGNORED_DIRS = {"__MACOSX", "node_modules", "__pycache__"}
# The MIT OpenCourseWare terms-of-use page at the end of each PDF.
BOILERPLATE = re.compile(r"For information about citing these materials or our Terms of Use", re.IGNORECASE)


class CoursePlugin(Plugin):
    """Default behavior: groups files by the lecture number in their name or folder."""

    # --- Settings (also settable from [settings] in coursesitetolectures.toml) ---

    unnumbered = "skip"  # documents with no lecture number: "skip", or "separate" for a lecture each
    ocw_types = ("Lecture Notes",)  # OpenCourseWare exports: the resource types to make lectures from
    # Course websites: patterns for the schedule columns to take materials from. The first finds the
    # schedule table and titles each lecture; add others such as "textbook|reading" for their links too.
    site_columns = ("lecture",)
    fetch_delay = 1.0  # seconds between requests to the same site

    # --- Which files, and which lecture each belongs to ---

    def include(self, rel):
        """Whether to use the file at rel (relative to the course directory)."""
        if any(part.startswith(".") or part in IGNORED_DIRS for part in rel.parts):
            return False
        return rel.suffix.lower() in DOC_EXTS | CODE_EXTS

    def lecture_number(self, rel):
        """The lecture number for a file, from its name or else its nearest folder, or None."""
        for part in [rel.stem, *reversed(rel.parent.parts)]:
            if m := LECTURE_NUMBER.search(part):
                return int(m.group(1))
        return None

    def lecture_title(self, number, files, detected):
        """The title of a lecture, given its number (None if unnumbered), its files, and the title found in
        an OpenCourseWare export's pages (None if none was found)."""
        if detected:
            return detected
        if number is None:
            return re.sub(r"[_\-]+", " ", files[0].stem).strip().title()
        return f"Lecture {number}"

    def output_name(self, lecture):
        """The stem of every file made from this lecture."""
        if lecture.number is None:
            return re.sub(r"[^A-Za-z0-9]+", "-", str(lecture.files[0].with_suffix(""))).strip("-")
        return f"lecture-{lecture.number:02d}"

    def order_files(self, files):
        """The order a lecture's files are presented in: documents, then code, each by path."""
        return sorted(files, key=lambda p: (p.suffix.lower() in CODE_EXTS, str(p)))

    def keep_section(self, section):
        """Whether to keep an extracted section; drops OpenCourseWare terms-of-use pages."""
        return not BOILERPLATE.search(section.body)

    # --- Prompts ---

    def vision_prompt(self):
        """The prompt sent with each scanned page image for transcription."""
        return """\
Transcribe this scanned page of course notes into Markdown.

- Write all mathematics in LaTeX: $...$ inline and $$...$$ for displayed equations.
- Keep the page's structure: headings, numbered equations, and lists. Write run-in labels such \
as "Theorem 3.", "Definition." or "Proof." in bold, even when the page underlines them. Rejoin lines that only wrapped because of the page width, and words \
hyphenated across lines.
- For a figure, write a short description in square brackets, such as [Figure: graph of \
y = x^2 between -1 and 1], including any labels on it.
- Leave out running headers and page numbers.
- Transcribe the words exactly; don't summarize or correct them.

Reply with the Markdown only."""

    def lecture_system(self):
        teaching = f"an experienced instructor teaching {self.course}" if self.course else "an experienced instructor"
        return (
            f"You are {teaching}. You write the word-for-word transcript of a recorded lecture that teaches "
            f"{self.audience} from the course's lecture notes, slides and example code. Listeners hear the "
            "lecture as audio, so everything must make sense spoken aloud."
        )

    def lecture_prompt(self, title, slides):
        return f"""\
Here are the course materials for "{title}" (lecture notes, slides, handouts and example code), \
one "## [N] Title" section per page, slide, heading or code file:

<materials>
{slides}
</materials>

Write the full lecture transcript that teaches this material.

Structure:
- Go through the sections in order. For every section, start with its heading exactly as given \
(for example "## [12] Example code: bfs.py"), followed by what you say while that page or slide is \
showing. Every section gets one, even if only a sentence or two, so the audio can follow along with \
the materials.
- Where a passage runs across pages, carry it on naturally in the next section.

Coverage:
- Teach every definition, idea, theorem, algorithm, example and worked problem in the notes and \
slides. Don't skip or lump together points to save time. Example code is the exception: see below.
- Explain why each point matters {self.relevance}, with brief examples where they help.

Math, code and figures:
- Listeners can't see the page. Say notation in words ("n log n", "the sum from i equals 1 to n of \
i squared") and explain what each formula means rather than just reading it.
- Example code files support the lecture rather than being taught line by line. Read them first \
and write the lecture around them: where a slide or page introduces an idea the code demonstrates, \
say so briefly ("the example code for today defines exactly this function"). In the code file's own \
section, summarize in a paragraph or two what the code does as a whole and which of the lecture's \
ideas it shows, then suggest the listener run it or try changing it. Don't walk through it line by \
line or read it aloud.
- For short code on a slide or page, explain what it does; read it aloud only where the exact \
syntax matters.
- Describe figures only as far as the text tells you what they show.

Accuracy:
- Stay faithful to the materials. Don't introduce results, numbers, dates or citations that \
aren't in them.
- Pass quickly over boilerplate such as license notices, headers and course logistics.

Style:
- Write natural, spoken prose addressed to the class: warm, clear and conversational, the way a \
good instructor talks. Use paragraphs rather than bullet points, and no Markdown other than the \
section headings. No stage directions other than brief cues in square brackets when needed, such as \
[pause to think].
- Connect sections with short transitions so the lecture flows as one talk.

Reply with the transcript only, starting with the first section's heading."""
