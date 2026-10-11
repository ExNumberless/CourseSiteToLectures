import json

from coursesitetolectures import CoursePlugin, cli, vision
from coursesitetolectures.extract import Section
from coursesitetolectures.materials import find_lectures
from coursesitetolectures.providers import ocw


def test_is_export(ocw_dir, course_dir):
    assert ocw.is_export(ocw_dir)
    assert not ocw.is_export(course_dir)
    assert ocw.course_title(ocw_dir) == "18.014 Calc"


def test_lectures_from_listed_rows_in_page_order(ocw_dir, capsys):
    lectures = find_lectures(CoursePlugin(), ocw_dir)
    assert [(lec.name, lec.title, [f.name for f in lec.files]) for lec in lectures] == [
        ("lecture-01", "A: Integers", ["def_ChAnotes.pdf"]),
        ("lecture-02", "B: Square roots", ["abc_ChBnotes.pdf"]),
    ]
    # The whole-course PDF is only linked from a paragraph; the problem set is another type.
    assert "1 file(s) not listed on any page skipped: ghi_course_notes.pdf" in capsys.readouterr().err


def test_unlisted_separate_and_other_types(ocw_dir):
    plugin = CoursePlugin()
    plugin.unnumbered = "separate"
    plugin.ocw_types = ["Lecture Notes", "Problem Sets"]
    names = [(lec.title, lec.number) for lec in find_lectures(plugin, ocw_dir)]
    assert names == [("A: Integers", 1), ("B: Square roots", 2), ("Ghi Course Notes", None), ("Jkl Pset1", None)]


def test_unknown_type_lists_available(ocw_dir):
    plugin = CoursePlugin()
    plugin.ocw_types = ["Lecture Videos"]
    try:
        find_lectures(plugin, ocw_dir)
    except SystemExit as e:
        assert "'Lecture Notes' (3), 'Problem Sets' (1)" in str(e)
    else:
        raise AssertionError("expected SystemExit")


def test_materials_marks_scanned_pages(ocw_dir, tmp_path, capsys):
    out = tmp_path / "out"
    cli.main(["materials", "--input", str(ocw_dir), "--out", str(out)])
    assert "1 scanned pages have no text" in capsys.readouterr().out
    md = (out / "materials" / "lecture-02.md").read_text()
    assert "## [4] abc_ChBnotes.pdf, page 2\n\n(Scanned page: run materials with --vision" in md
    course = json.loads((out / "course.json").read_text())
    assert course["title"] == "18.014 Calc"  # from the export when the course setting is unset
    assert course["lectures"][1]["sections"][-1]["locator"] == "page 2"


def test_vision_uses_cache_and_sets_title(ocw_dir, tmp_path, capsys):
    out = tmp_path / "out"
    cached = out / "materials" / ".cache" / "static_resources_abc_ChBnotes.pdf" / "page-2.md"
    cached.parent.mkdir(parents=True)
    cached.write_text("## Theorem 1\n\n$\\sqrt{2}$ is irrational.\n")
    cli.main(["materials", "--vision", "--input", str(ocw_dir), "--out", str(out)])
    assert "1 scanned pages, 0 to transcribe" in capsys.readouterr().out
    md = (out / "materials" / "lecture-02.md").read_text()
    assert "## [4] Theorem 1\n\n### Theorem 1\n\n$\\sqrt{2}$ is irrational.\n" in md


def test_vision_titles():
    def title(text):
        section = Section("x.pdf, page 3", "", "x.pdf", "page 3", scanned=True)
        vision.apply(section, text)
        return section.title

    assert title("## The $\\epsilon$ test\n\nText.") == "The \\epsilon test"
    assert title(
        "proof ends.\n\n**Theorem 6.** *If $a$.*\n\n**Definition.** X. **Theorem 7.** Y.\n\n**Step 1.** Z."
    ) == ("Theorem 6, Definition, Theorem 7, …")
    assert title("Then $a^n$ is defined.\n\n<u>Theorem 10</u>. $a^n a^m$.\n\n<u>Proof</u>. Let") == "Theorem 10, Proof"
    assert title("Use **only** the axioms; then the theorem is proved.") == "Page 3"  # emphasis, not a label
