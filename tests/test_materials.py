import json
from pathlib import Path

import pytest

from coursesitetolectures import CoursePlugin, cli
from coursesitetolectures.extract import extract
from coursesitetolectures.materials import find_lectures, load


@pytest.mark.parametrize(
    "path, number",
    [
        ("MIT6_006F11_lec01.pdf", 1),
        ("Lecture 12 - Graphs.pdf", 12),
        ("week_3/notes.md", 3),
        ("lecture02/bfs.py", 2),
        ("slides/L05.pdf", 5),
        ("tutorial3.pdf", None),
        ("ps1.pdf", None),
    ],
)
def test_lecture_number(path, number):
    assert CoursePlugin().lecture_number(Path(path)) == number


def test_find_lectures_groups_and_orders(course_dir, capsys):
    lectures = find_lectures(CoursePlugin(), course_dir)
    assert [(lec.name, lec.title) for lec in lectures] == [
        ("lecture-01", "Lecture 1"),
        ("lecture-02", "Lecture 2"),
        ("lecture-03", "Lecture 3"),
        ("lecture-04", "Lecture 4"),
    ]
    # Documents before code.
    assert [f.as_posix() for f in lectures[1].files] == ["lecture02/notes.md", "lecture02/bfs.py"]
    assert "2 file(s) with no lecture number skipped" in capsys.readouterr().err


def test_unnumbered_separate(course_dir):
    plugin = CoursePlugin()
    plugin.unnumbered = "separate"
    names = [lec.name for lec in find_lectures(plugin, course_dir)]
    assert names[4:] == ["syllabus", "tutorial3"]


def test_sections_numbered_across_course_without_boilerplate(course_dir):
    lectures = find_lectures(CoursePlugin(), course_dir)
    load(CoursePlugin(), lectures, course_dir)
    titles = [[(n, s.title, s.locator) for n, s in lec.sections] for lec in lectures]
    assert titles == [
        [(1, "Introduction", "page 1"), (2, "Peak Finding", "page 2")],
        [
            (3, "notes", "section 1"),
            (4, "Graphs", "section 2"),
            (5, "BFS", "section 3"),
            (6, "Example code: bfs.py", None),
        ],
        [(7, "Sorting", "cell 1"), (8, "Merge sort", "cell 3")],
        [(9, "Hashing", "slide 1"), (10, "Chaining", "slide 2")],
    ]
    page1 = lectures[0].sections[0][1]
    assert page1.body == "Introduction\nAlgorithms solve problems."  # page number dropped
    sorting = lectures[2].sections[0][1]
    assert "```python\nsorted([3, 1, 2])\n```" in sorting.body


def test_pptx_includes_speaker_notes(course_dir):
    [hashing, chaining] = extract(course_dir / "Lecture 4 - Hashing.pptx", "x.pptx")
    assert hashing.body == "Hash tables\n\nSpeaker notes:\n\nSay hello."
    assert chaining.body == "Lists"


def test_html_splits_at_headings_and_drops_navigation(course_dir):
    sections = extract(course_dir / "syllabus.html", "syllabus.html")
    assert [(s.title, s.body) for s in sections] == [("Syllabus", "Weekly problem sets."), ("Grading", "Exams.")]


def test_materials_writes_markdown_and_index(course_dir, tmp_path):
    out = tmp_path / "out"
    cli.main(["materials", "--input", str(course_dir), "--out", str(out)])

    md = (out / "materials" / "lecture-01.md").read_text()
    assert md.startswith("# Lecture 1\n\n## [1] Introduction\n\nIntroduction\nAlgorithms solve problems.\n\n")
    assert "## [2] Peak Finding" in md

    course = json.loads((out / "course.json").read_text())
    assert course["title"] == "course"
    lec2 = course["lectures"][1]
    assert lec2["materials"] == "materials/lecture-02.md"
    assert lec2["audio"] == "audio/lecture-02.mp3"
    assert lec2["sections"][-1] == {
        "n": 6,
        "title": "Example code: bfs.py",
        "source": "lecture02/bfs.py",
        "locator": None,
    }


def test_materials_selected_lecture_keeps_course_numbering(course_dir, tmp_path):
    out = tmp_path / "out"
    cli.main(["materials", "3", "--input", str(course_dir), "--out", str(out)])
    assert [p.name for p in (out / "materials").iterdir()] == ["lecture-03.md"]
    assert "## [7] Sorting" in (out / "materials" / "lecture-03.md").read_text()


def test_output_inside_input_is_ignored(course_dir):
    out = course_dir / "out"
    cli.main(["materials", "--input", str(course_dir), "--out", str(out)])
    cli.main(["materials", "--input", str(course_dir), "--out", str(out)])
    assert len(json.loads((out / "course.json").read_text())["lectures"]) == 4


def test_dry_run_writes_nothing(course_dir, tmp_path, capsys):
    cli.main(["materials", "--dry-run", "--input", str(course_dir), "--out", str(tmp_path / "out")])
    assert "lecture-02: Lecture 2 [3-6]" in capsys.readouterr().out
    assert not (tmp_path / "out").exists()


def test_config_settings_and_plugin(course_dir, tmp_path, monkeypatch):
    (tmp_path / "my_plugin.py").write_text(
        "from coursesitetolectures import CoursePlugin\n\n"
        "class MyPlugin(CoursePlugin):\n"
        "    def lecture_title(self, number, files):\n"
        "        return f'Session {number}' if number else super().lecture_title(number, files)\n"
    )
    (tmp_path / "coursesitetolectures.toml").write_text(
        'plugin = "my_plugin.py"\ninput = "course"\n\n[settings]\nunnumbered = "separate"\ncourse = "Algorithms"\n'
    )
    monkeypatch.chdir(tmp_path)
    cli.main(["materials"])
    course = json.loads((tmp_path / "out" / "course.json").read_text())
    assert course["title"] == "Algorithms"
    assert [lec["title"] for lec in course["lectures"]][:2] == ["Session 1", "Session 2"]
    assert len(course["lectures"]) == 6


def test_lecture_prompt_uses_settings():
    plugin = CoursePlugin()
    plugin.course = "MIT 6.006"
    assert "teaching MIT 6.006" in plugin.lecture_system()
    assert "## [1] Intro" in plugin.lecture_prompt("Lecture 1", "## [1] Intro")
