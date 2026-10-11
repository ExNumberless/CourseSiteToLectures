import json

import jsonschema
import pymupdf
import pytest
from PIL import Image
from referencing import Registry, Resource

from coursesitetolectures import cli, slides


@pytest.fixture
def no_soffice(monkeypatch):
    monkeypatch.setattr(slides, "find_soffice", lambda: None)


def render(out, name):
    return json.loads(slides.render(out / "course.json", name).read_text())


def summary(deck):
    return [(s["n"], s["kind"], s["title"], s["locator"]) for s in deck["slides"]]


def validator(path):
    schemas = [json.loads(p.read_text()) for p in (slides.SLIDES_SCHEMA, slides.PLAYER_SCHEMA)]
    registry = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas)
    schema = json.loads(path.read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema, registry=registry)


def test_slides_json_matches_schema(slides_course, no_soffice):
    _, out = slides_course
    schema = validator(slides.SLIDES_SCHEMA)
    for name in ("lecture-01", "lecture-02", "lecture-03", "lecture-04"):
        deck = render(out, name)
        schema.validate(deck)
        assert not (out / "slides" / name / "player.json").exists()  # the assemble step's file
    deck["slides"][0]["narration"] = "Hello."
    assert not schema.is_valid(deck)


def test_player_schema_extends_slides_schema(slides_course, no_soffice):
    _, out = slides_course
    schema = validator(slides.PLAYER_SCHEMA)
    deck = render(out, "lecture-02")
    assert not schema.is_valid(deck)
    timed = {"narration": "Hello.", "start_ms": 0, "end_ms": 1500}
    player = {**deck, "audio": "../../audio/lecture-02.mp3", "slides": [{**s, **timed} for s in deck["slides"]]}
    schema.validate(player)
    for bad in ({"start_ms": None}, {"narration": None}, {"extra": 1}):
        assert not schema.is_valid({**player, "slides": [{**player["slides"][0], **bad}]})
    assert not schema.is_valid({**player, "audio": None})
    assert not schema.is_valid({**player, "extra": 1})
    del player["slides"][0]["markdown"]
    assert not schema.is_valid(player)  # the slides schema's per-kind rules still apply


def test_pdf_pages_become_images(slides_course, no_soffice):
    _, out = slides_course
    deck = render(out, "lecture-01")
    assert deck["name"] == "lecture-01" and deck["title"] == "Lecture 1" and deck["number"] == 1
    assert summary(deck) == [(1, "image", "Limits", "page 1"), (2, "image", "lec01.pdf, page 2", "page 2")]
    for s in deck["slides"]:
        assert s["image"] == f"{s['n']}.webp"
        assert not {"narration", "start_ms", "end_ms"} & set(s)
        with Image.open(out / "slides" / "lecture-01" / s["image"]) as image:
            assert image.format == "WEBP"
            assert image.size == (s["width"], s["height"]) == (1240, 1755)  # A4 at 150 dpi


def test_markdown_and_code_slides(slides_course, no_soffice):
    _, out = slides_course
    deck = render(out, "lecture-02")
    assert summary(deck) == [
        (3, "markdown", "Recursion", "section 1"),
        (4, "markdown", "Base cases", "section 2"),
        (5, "markdown", "Trees", "section 1"),
        (6, "code", "Example code: fact.py", None),
    ]
    recursion, base, trees, code = deck["slides"]
    assert recursion["markdown"] == "A function that calls itself."  # without the speaker notes
    assert base["markdown"] == "\\# stop here"
    assert trees["markdown"] == "Leaves and roots."
    assert code["language"] == "python"
    assert code["code"] == "def fact(n):\n    return 1 if n == 0 else n * fact(n - 1)"
    assert not list((out / "slides" / "lecture-02").glob("*.webp"))


def test_notebook_slides(slides_course, no_soffice):
    _, out = slides_course
    [cell] = render(out, "lecture-03")["slides"]
    assert (cell["kind"], cell["title"], cell["locator"]) == ("markdown", "Sorting", "cell 1")
    assert cell["markdown"] == "Insertion sort, $O(n^2)$.\n\n```python\nsorted([3, 1, 2])\n```"


def test_pptx_without_libreoffice_is_markdown(slides_course, no_soffice):
    _, out = slides_course
    deck = render(out, "lecture-04")
    assert summary(deck) == [(8, "markdown", "Hashing", "slide 1"), (9, "markdown", "Chaining", "slide 2")]
    assert [s["markdown"] for s in deck["slides"]] == ["Hash tables", "Lists"]


def test_pptx_with_libreoffice_is_images(slides_course, monkeypatch):
    _, out = slides_course
    converted = []

    def pptx_to_pdf(path, out_dir, soffice):
        converted.append((path.name, soffice))
        out_dir.mkdir(parents=True)
        doc = pymupdf.open()
        for _ in range(2):
            doc.new_page(width=720, height=405)
        doc.save(out_dir / "deck.pdf")
        return out_dir / "deck.pdf"

    monkeypatch.setattr(slides, "find_soffice", lambda: "soffice")
    monkeypatch.setattr(slides, "pptx_to_pdf", pptx_to_pdf)
    deck = render(out, "lecture-04")
    assert converted == [("Lecture 4 - Hashing.pptx", "soffice")]  # once per deck
    assert summary(deck) == [(8, "image", "Hashing", "slide 1"), (9, "image", "Chaining", "slide 2")]
    assert (deck["slides"][0]["width"], deck["slides"][0]["height"]) == (1500, 844)


def test_failed_conversion_falls_back_to_markdown(slides_course, monkeypatch):
    _, out = slides_course
    monkeypatch.setattr(slides, "find_soffice", lambda: "soffice")
    monkeypatch.setattr(slides, "pptx_to_pdf", lambda path, out_dir, soffice: None)
    assert {s["kind"] for s in render(out, "lecture-04")["slides"]} == {"markdown"}


@pytest.mark.skipif(slides.find_soffice() is None, reason="LibreOffice is not installed")
def test_pptx_with_real_libreoffice(slides_course):
    _, out = slides_course
    assert [s["kind"] for s in render(out, "lecture-04")["slides"]] == ["image", "image"]


def test_rerender_removes_stale_images(slides_course, no_soffice):
    _, out = slides_course
    stale = out / "slides" / "lecture-01" / "99.webp"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")
    render(out, "lecture-01")
    assert sorted(p.name for p in stale.parent.iterdir()) == ["1.webp", "2.webp", "slides.json"]


def test_render_options(slides_course, tmp_path, no_soffice):
    course, out = slides_course
    moved = tmp_path / "moved"
    course.rename(moved)  # the materials are somewhere other than course.json says
    path = slides.render(out / "course.json", "lecture-02", tmp_path / "deck", input_dir=moved)
    assert path == tmp_path / "deck" / "slides.json"
    assert json.loads(path.read_text())["slides"][-1]["kind"] == "code"
    with pytest.raises(SystemExit, match="no lecture named 'lecture-09'"):
        slides.render(out / "course.json", "lecture-09")


def test_cli(slides_course, no_soffice, capsys):
    course, out = slides_course
    cli.main(["slides", "--input", str(course), "--out", str(out), "1", "lecture-03"])
    assert sorted(p.name for p in (out / "slides").iterdir()) == ["lecture-01", "lecture-03"]
    assert "lecture-01: 2 image ->" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="no lecture named '7'"):
        cli.main(["slides", "--out", str(out), "7"])
