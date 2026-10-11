# CourseSiteToLectures

Turn course materials, such as an [MIT OpenCourseWare](https://ocw.mit.edu) download, a folder of notes and slides, or a course website (live or archived on the Wayback Machine), into:

- **Lecture materials**: a Markdown file per lecture, gathering its lecture notes, slides, handouts, notebooks and example code, with one `## [N] Title` section per page, slide, heading or code file.
- **Lecture transcripts**: a spoken, word-for-word lecture per lecture, written by Claude to teach every section, with math and code explained in words.
- **Narrated audio**: an MP3 per lecture with a chapter per section, using Speechify text-to-speech.
- **A course index** (`course.json`): every lecture, its files, and the source file and page or slide for each section number, so a player can show the matching page while the audio plays.

The transcript and audio steps come from [SlidesToLectures](https://github.com/ExNumberless/SlidesToLectures), which does the same for a folder of slideshow PDFs; this package adds materials providers, which find a course's lectures, and extraction of their files.

## Install

```bash
uv tool install "coursesitetolectures[tts]"
```

or `pip install "coursesitetolectures[tts]"`. Leave off `[tts]` if you don't need audio. Requires Python 3.11+.

- The `lecture` step, and `materials --vision`, call the Claude API: set `ANTHROPIC_API_KEY`.
- The `tts` step needs `SPEECHIFY_API_KEY` and [ffmpeg](https://ffmpeg.org/) on your `PATH`.

## Quick start

```bash
course-site-to-lectures fetch https://inst.eecs.berkeley.edu/~cs61a/su19/ --wayback 2019   # only for websites
course-site-to-lectures materials --input course --dry-run   # check how files were grouped
course-site-to-lectures materials --input course             # out/materials/ and out/course.json
course-site-to-lectures lecture                              # out/lectures/
course-site-to-lectures tts                                  # out/audio/
```

Every command takes `--input DIR` (the course materials), `--out DIR` (default `out`), `--provider`, `--plugin` and `--config`. Source files are never modified. Run `course-site-to-lectures <command> --help` for each command's options:

| Command | What it does | Notable options |
|---|---|---|
| `fetch` | Download a course website's lecture materials into a directory (default `courses/<name>`) | `--wayback TIME`, `--force` |
| `materials` | Group files into lectures; write each lecture's materials and `course.json` | `--dry-run` lists lectures and files; `--vision` transcribes scanned pages; lecture names or numbers to process only some |
| `lecture` | Lecture transcript per lecture from its materials | `--model`, `--force` |
| `tts` | Narrated MP3 per lecture; audio cached per request | `--voice`, `--rps`, `--concurrency`, `--force` |

Lecture transcripts are plain Markdown: read and edit them before running `tts`. Re-running `tts` with `--force` only re-synthesizes the parts you changed.

## Examples

The two courses this was tested on. Each run makes a transcript and audio for lecture 1 only, which is cheap to try; leave off the lecture and file arguments to do every lecture.

**MIT 18.014 Calculus with Theory**, an OpenCourseWare export of scanned notes. Download the course from [its OCW page](https://ocw.mit.edu/courses/18-014-calculus-with-theory-fall-2010/), then:

```bash
unzip 18.014-fall-2010.zip -d 18.014-fall-2010
course-site-to-lectures materials --input 18.014-fall-2010 --out out/18.014 --vision 1
course-site-to-lectures lecture --out out/18.014 out/18.014/materials/lecture-01.md
course-site-to-lectures tts --out out/18.014 out/18.014/lectures/lecture-01.md
```

The notes are scanned, so `--vision` transcribes their pages with Claude; `1` limits materials to chapter A.

**Berkeley CS 61A Summer 2019**, a course website read from the Wayback Machine, whose Google Slides decks have since been deleted:

```bash
course-site-to-lectures fetch https://inst.eecs.berkeley.edu/~cs61a/su19/ --wayback 2019
course-site-to-lectures materials --input courses/cs61a-su19 --out out/cs61a-su19
course-site-to-lectures lecture --out out/cs61a-su19 out/cs61a-su19/materials/lecture-01.md
course-site-to-lectures tts --out out/cs61a-su19 out/cs61a-su19/lectures/lecture-01.md
```

`fetch` downloads into `courses/cs61a-su19` and rebuilds the deleted decks from archived copies.

## Materials providers

A provider knows one kind of course source and how to find its lectures. The built-in providers, in the order they're detected:

| Provider | Source | Lectures |
|---|---|---|
| `website` | A course website's URL, used by `fetch` | Rows of the site's schedule table |
| `manifest` | A directory `fetch` downloaded into (it has a `lectures.json`) | As fetched |
| `ocw` | An unzipped MIT OpenCourseWare export | The export's own metadata |
| `folder` | Any other directory | The lecture number in each file's name |

Name one with `--provider` or `provider = ...` in the config to skip detection. See below for writing your own.

### Course websites

`fetch` reads a course's home page and finds the schedule: the first table with a column headed like "Lecture". Each row with links in that column becomes a lecture, and `fetch` downloads what the row links to: PDFs, slides (Google Slides and Docs as PDF), notebooks, code and pages. Videos and other links are recorded in `lectures.json` and `course.json` but not downloaded. Set `site_columns` to take materials from more columns, such as `["lecture", "textbook|reading", "discussion"]`.

Old course sites are often gone or behind a login. Pass `--wayback 2019` (or a `web.archive.org/web/...` URL) to read the course from the [Wayback Machine](https://web.archive.org): the [CDX API](https://archive.org/developers/wayback-cdx-server.html) lists what was captured, the site's own pages and files come from the capture nearest that time, and other sites are tried live first, then in the archive. Files that can't be fetched are reported and skipped.

Google Slides decks that have since been deleted or made private are recovered from the archive too: an archived PDF export if there is one, or else the slides' text and speaker notes, rebuilt from an archived copy of the deck's editor page into Markdown with a section per slide. No archive.org account or keys are needed.

`fetch` follows each site's robots.txt and waits `fetch_delay` seconds between requests to a site. Re-running it only downloads what's missing, unless you pass `--force`. Then run `materials --input` on the directory, as with any other course.

### Course folders

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
| `site_columns` | `["lecture"]` | Course websites: patterns for the schedule columns to take materials from |
| `fetch_delay` | `1.0` | Course websites: seconds between requests to a site |
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

## Writing a provider

A provider is a subclass of `coursesitetolectures.Provider`:

| Method | Does |
|---|---|
| `detect(source)` | Whether it handles `source`: a local directory `Path`, or a URL string for `fetch` |
| `lectures(plugin, input_dir, exclude)` | The lectures, as `Lecture` objects with files relative to `input_dir` |
| `fetch(plugin, url, dest, **options)` | Online providers (`online = True`): download a course into `dest` and write `lectures.json` with `providers.manifest.write` |
| `course_title(input_dir)` | The course's title, when the source knows it |

An online provider can subclass `providers.manifest.ManifestProvider` to read back what it fetched, and use `providers.web.Web` for polite HTTP requests with Wayback Machine support. See [examples/example_provider.py](examples/example_provider.py).

To warn about skipped files, call `report.warn(self.reporter, message)` rather than printing, so programs that call the library get the message through their reporter. `fetch` can also take a `reporter` option.

Use a provider with `--provider my_provider.py[:Class]` or `--provider package.module:Class`, or publish it in a package under the `coursesitetolectures.providers` entry point group, which makes it available by name and tried first in detection:

```toml
[project.entry-points."coursesitetolectures.providers"]
mysite = "my_package.providers:MySiteProvider"
```

## Progress and usage

`materials.run`, `vision.run` and `WebsiteProvider.fetch` take an optional `reporter`: any object with the methods of `coursesitetolectures.Reporter` (the same protocol as SlidesToLectures'). It receives `step(name, done, total)` for progress (a call with `done` 0 and the step's name starts each step; after that, `name` is the item just finished), `log(message)` for what the CLI prints, and `usage("anthropic", model, input_tokens=..., output_tokens=..., cache_read_tokens=...)` for each Claude request. A reporter can also have `warn(message)` for what the CLI prints to stderr. The default, `PrintReporter`, prints as the CLI does.

## Course materials and licenses

Course materials keep their own licenses, and course websites often have no open license at all, so keep what you fetch for your own study. MIT OpenCourseWare, for example, is [CC BY-NC-SA](https://ocw.mit.edu/pages/privacy-and-terms-of-use/): audio you make from it is an adaptation, so share it only non-commercially, with attribution and under the same license.

## Development

```bash
uv sync --all-extras
uv run pytest
uv run ruff check .
```

With [mise](https://mise.jdx.dev/), `mise run install`, `mise run test`, `mise run lint` and `mise run build` do the same.

### Releasing

Bump `version` in `pyproject.toml` and publish a GitHub release tagged `v<version>`. The Release workflow builds the package and publishes it to PyPI with trusted publishing.

## License

[MIT](LICENSE)
