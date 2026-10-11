from types import SimpleNamespace

import anthropic
from test_providers import SITE, FakeWeb, site_pages

from coursesitetolectures import CoursePlugin, cli, config, materials
from coursesitetolectures.providers.website import WebsiteProvider


class RecordingReporter:
    """Records every call; warnings go to log, as for any reporter without warn."""

    def __init__(self):
        self.steps, self.logs, self.usages = [], [], []

    def step(self, name, done, total):
        self.steps.append((name, done, total))

    def log(self, message):
        self.logs.append(message)

    def usage(self, vendor, model, **counts):
        self.usages.append((vendor, model, counts))


def test_materials_reports_instead_of_printing(course_dir, tmp_path, capsys):
    cfg = config.load(None, None, course_dir, tmp_path / "out", None)
    reporter = RecordingReporter()
    materials.run(cfg, reporter=reporter)
    assert capsys.readouterr() == ("", "")
    assert reporter.steps == [("materials", 0, 4)] + [(f"lecture-0{i}", i, 4) for i in range(1, 5)]
    assert reporter.logs[0].startswith("2 file(s) with no lecture number skipped")
    assert reporter.logs[1].startswith("1 file(s), 2 sections -> ")
    assert reporter.logs[-1].startswith("-> ")
    assert reporter.usages == []


def test_default_reporter_prints_as_before(course_dir, tmp_path, capsys):
    cli.main(["materials", "--input", str(course_dir), "--out", str(tmp_path / "out")])
    out, err = capsys.readouterr()
    assert err.startswith("2 file(s) with no lecture number skipped")
    assert out.splitlines()[0].startswith("1 file(s), 2 sections -> ")
    assert out.splitlines()[-1].startswith("-> ")


def test_fetch_reports_instead_of_printing(tmp_path, capsys):
    reporter = RecordingReporter()
    WebsiteProvider().fetch(CoursePlugin(), SITE, tmp_path / "c", web=FakeWeb(site_pages()), reporter=reporter)
    assert capsys.readouterr() == ("", "")
    assert reporter.steps == [("fetch", 0, 2), ("Intro", 1, 2), ("Functions", 2, 2)]
    assert "1. Intro: 2 file(s), 3 link(s)" in reporter.logs
    assert any("couldn't fetch https://docs.google.com/presentation/d/GONE/edit" in m for m in reporter.logs)


class FakeMessages:
    def __init__(self):
        self.calls = 0

    async def create(self, model, **kwargs):
        self.calls += 1
        return SimpleNamespace(
            model=model,
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="## Square roots\n\nRoot two.")],
            usage=SimpleNamespace(input_tokens=1500, output_tokens=40, cache_read_input_tokens=None),
        )


class FakeClient:
    def __init__(self):
        self.beta = SimpleNamespace(messages=FakeMessages())

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass


def test_vision_reports_usage_per_request(ocw_dir, tmp_path, capsys, monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda: client)
    cfg = config.load(None, None, ocw_dir, tmp_path / "out", None)
    reporter = RecordingReporter()
    materials.run(cfg, vision=True, model="claude-test", reporter=reporter)
    assert capsys.readouterr() == ("", "")
    assert client.beta.messages.calls == 1
    assert reporter.usages == [
        ("anthropic", "claude-test", {"input_tokens": 1500, "output_tokens": 40, "cache_read_tokens": 0})
    ]
    assert reporter.steps[:2] == [("vision", 0, 1), ("[4] lecture-02 page 2", 1, 1)]
    assert "1 scanned pages, 1 to transcribe with Claude" in reporter.logs
    assert "  [4] lecture-02 page 2" in reporter.logs
    assert "## [4] Square roots" in (tmp_path / "out" / "materials" / "lecture-02.md").read_text()
