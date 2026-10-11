# CourseSiteToLectures

Turns course websites, Wayback Machine archives, OCW exports and folders into lecture materials, then lecture transcripts and narrated audio (through SlidesToLectures). Published to PyPI as `coursesitetolectures`. README.md is the user documentation.

[LectureCast](https://github.com/ExNumberless/LectureCast) is a hosted web app built on this
library and SlidesToLectures. Its Phase 0 changes here are issues in the
"Phase 0: LectureCast support (0.2.0)" milestone; the design is in LectureCast's
[docs/plan/phase0-libraries.md](https://github.com/ExNumberless/LectureCast/blob/main/docs/plan/phase0-libraries.md).

## Conventions

- mise and uv: `mise run install`, `mise run test`, `mise run lint`, `mise run format`.
  CI runs ruff format, ruff check and pytest on Python 3.11 and 3.13.
- The CLI must keep working unchanged: library APIs gain optional parameters with defaults that
  behave as before.
- Releases: bump `version` in pyproject.toml and publish a GitHub release tagged
  `v<version>`; the Release workflow publishes to PyPI with trusted publishing.

## Workflow

- One branch per issue, named as the issue says. Check the issue's "Needs first" list is merged
  before starting.
- `main` is protected: open a PR that closes its issue (`Closes #N`) and passes CI. Addison
  reviews and squash-merges; never merge or enable auto-merge yourself.
- Start everything you post to GitHub with "[POSTED BY AI AGENT]": PR and issue titles and
  bodies, comments and reviews, so readers can tell an AI agent wrote it.
