# CourseSiteToLectures

Turn a folder of course materials, such as an [MIT OpenCourseWare](https://ocw.mit.edu) download, into:

- **Lecture materials**: a Markdown file per lecture, gathering its lecture notes, slides, handouts, notebooks and example code, with one `## [N] Title` section per page, slide, heading or code file.
- **Lecture transcripts**: a spoken, word-for-word lecture per lecture, written by Claude to teach every section, with math and code explained in words.
- **Narrated audio**: an MP3 per lecture with a chapter per section, using Speechify text-to-speech.
- **A course index** (`course.json`): every lecture, its files, and the source file and page or slide for each section number, so a player can show the matching page while the audio plays.

The transcript and audio steps come from [SlidesToLectures](https://github.com/ExNumberless/SlidesToLectures), which does the same for a folder of slideshow PDFs; this package adds course-folder discovery and extraction.

## Install

```bash
uv tool install "coursesitetolectures[tts]"
```

or `pip install "coursesitetolectures[tts]"`. Leave off `[tts]` if you don't need audio. Requires Python 3.11+.

- The `lecture` step, and `materials --vision`, call the Claude API: set `ANTHROPIC_API_KEY`.
- The `tts` step needs `SPEECHIFY_API_KEY` and [ffmpeg](https://ffmpeg.org/) on your `PATH`.

## Quick start

```bash
course-site-to-lectures materials --input course --dry-run   # check how files were grouped
course-site-to-lectures materials --input course             # out/materials/ and out/course.json
course-site-to-lectures lecture                              # out/lectures/
course-site-to-lectures tts                                  # out/audio/
```

Every command takes `--input DIR` (the course materials), `--out DIR` (default `out`), `--plugin` and `--config`. Source files are never modified. Run `course-site-to-lectures <command> --help` for each command's options:

| Command | What it does | Notable options |
|---|---|---|
| `materials` | Group files into lectures; write each lecture's materials and `course.json` | `--dry-run` lists lectures and files; `--vision` transcribes scanned pages; lecture names or numbers to process only some |
| `lecture` | Lecture transcript per lecture from its materials | `--model`, `--force` |
| `tts` | Narrated MP3 per lecture; audio cached per request | `--voice`, `--rps`, `--concurrency`, `--force` |

Lecture transcripts are plain Markdown: read and edit them before running `tts`. Re-running `tts` with `--force` only re-synthesizes the parts you changed.

## How files become lectures

Files are grouped by the lecture number in their name, or else in their nearest folder: `MIT6_006F11_lec01.pdf`, `Lecture 3 - Graphs.pptx`, `week2/notes.md` and `lecture04/bfs.py` all work. Within a lecture, documents come first, then code. Files with no lecture number are skipped, or each becomes a lecture of its own with `unnumbered = "separate"`.

| File type | One section per |
|---|---|
| PDF (`.pdf`) | Page (pages with no text are skipped) |
| PowerPoint (`.pptx`) | Slide, including speaker notes |
| HTML (`.html`), Markdown (`.md`), LaTeX (`.tex`) | Top-level heading |
| Jupyter notebook (`.ipynb`) | Markdown heading cell, with the code cells after it |
| Code (`.py`, `.java`, `.c`, `.js`, ...) and text (`.txt`) | File |

PDF pages that are scanned images, with no text layer, are transcribed by Claude with `--vision`, with math written in LaTeX. Transcriptions are cached per page in `<materials dir>/.cache/`, so re-runs only transcribe new pages. `--dry-run` reports how many scanned pages each lecture has.

Sections are numbered across the whole course, so numbers stay the same when you process only some lectures. MIT OpenCourseWare's terms-of-use pages are left out.

### MIT OpenCourseWare exports

When the input is an unzipped [OpenCourseWare](https://ocw.mit.edu) course download, lectures come from the export's own metadata instead of file names:

- Files are chosen by their OCW resource type, `Lecture Notes` by default. Set `ocw_types` to use others, such as `["Lecture Notes", "Lecture Slides"]`; a type with no files lists the types the course has.
- Each table row or list item on the course's pages that links to those files becomes a lecture, in page order, titled from the row: for example `C: The Riemann condition`. Several files linked from one row, such as a session's notes and slides, make one lecture.
- Files that no row lists, such as a single PDF of the whole set of notes, are skipped, or each becomes a lecture of its own with `unnumbered = "separate"`.
- `course` defaults to the course number and title, such as `18.014 Calculus with Theory`.

## Configuration

Put a `coursesitetolectures.toml` in the directory you run from (or pass `--config`), so you don't have to repeat options:

```toml
plugin = "my_plugin.py"   # optional, see below
input = "6.006"
output = "out"

[output_dirs]             # optional: put individual outputs elsewhere
audio = "podcast"

[settings]                # plugin settings
course = "MIT 6.006 Introduction to Algorithms"
audience = "undergraduates who know some Python"
```

Settings:

| Setting | Default | Used for |
|---|---|---|
| `course` | none | What the lectures teach, in the lecture prompt; the course title in `course.json` |
| `audience` | `"a class"` | Who the lecture is presented to |
| `relevance` | `"in practice"` | The lecture explains why each point matters *relevance* |
| `unnumbered` | `"skip"` | Files with no lecture number (or not listed on an OCW page): `"skip"`, or `"separate"` for a lecture each |
| `ocw_types` | `["Lecture Notes"]` | OpenCourseWare exports: the resource types to make lectures from |
| `vision_model`, `lecture_model` | `claude-opus-5-5` | Claude models |
| `tts_voice` | `henry` | Speechify voice |

## Plugins

When settings aren't enough, such as to choose which files to use or to title lectures, write a plugin: a subclass of `coursesitetolectures.CoursePlugin` that overrides the hooks you need. Call `super()` to wrap the default behavior. See [examples/example_plugin.py](examples/example_plugin.py).

Use it with `--plugin my_plugin.py`, `--plugin my_plugin.py:MyPlugin`, `--plugin package.module:MyPlugin`, or `plugin = ...` in the config.

| Hook | Default |
|---|---|
| `include(rel)` | Supported file types, skipping hidden folders |
| `lecture_number(rel)` | The number after `lec`, `lecture`, `session`, `week`, `class`, `unit` or `L` in the name or nearest folder |
| `lecture_title(number, files, detected)` | The title from an OCW page, else `Lecture N` |
| `output_name(lecture)` | `lecture-NN` |
| `order_files(files)` | Documents, then code, each by path |
| `keep_section(section)` | Everything but OpenCourseWare terms-of-use pages |
| `vision_prompt()`, `lecture_system()`, `lecture_prompt(title, materials)` | Built from the settings |

## Course materials and licenses

Course materials keep their own licenses. MIT OpenCourseWare, for example, is [CC BY-NC-SA](https://ocw.mit.edu/pages/privacy-and-terms-of-use/): audio you make from it is an adaptation, so share it only non-commercially, with attribution and under the same license.

## Development

```bash
uv sync --all-extras
uv run pytest
uv run ruff check .
```

With [mise](https://mise.jdx.dev/), `mise run install`, `mise run test`, `mise run lint` and `mise run build` do the same.

### Releasing

`slidestolectures` must be on PyPI first. Then remove `[tool.uv.sources]` from `pyproject.toml`, bump `version`, and publish a GitHub release tagged `v<version>`. The Release workflow builds the package and publishes it to PyPI with trusted publishing.

## License

[MIT](LICENSE)
