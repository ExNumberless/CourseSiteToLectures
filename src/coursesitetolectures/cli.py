"""Command-line interface: course-site-to-lectures <command> [options]."""

import argparse
from pathlib import Path

from slidestolectures.cli import markdown_files

from . import __version__, config

COMMANDS = {
    "materials": "group course files into lectures and write each lecture's materials as Markdown",
    "lecture": "write a spoken lecture transcript for each lecture's materials with Claude",
    "tts": "narrate each lecture transcript into an MP3 with Speechify",
}


def parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=Path, help=f"config file (default: ./{config.CONFIG_NAME} if present)")
    common.add_argument("--plugin", help="plugin as module:Class or path/to/file.py[:Class]")
    common.add_argument("--input", type=Path, help="directory of course materials")
    common.add_argument("--out", type=Path, help="base directory for generated files (default: out)")

    p = argparse.ArgumentParser(
        prog="course-site-to-lectures",
        description="Turn a folder of course materials into lecture transcripts and narrated audio.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True, metavar="command")
    cmd = {name: sub.add_parser(name, parents=[common], help=text, description=text) for name, text in COMMANDS.items()}

    cmd["materials"].add_argument("lectures", nargs="*", help="only these lectures (name or number)")
    cmd["materials"].add_argument("--dry-run", action="store_true", help="list the lectures and their files only")
    cmd["materials"].add_argument(
        "--vision", action="store_true", help="transcribe scanned pages (no text layer) with Claude; cached per page"
    )
    cmd["materials"].add_argument("--model", help="Claude model for --vision (default: the plugin's vision_model)")

    cmd["lecture"].add_argument(
        "files", nargs="*", type=Path, help="materials Markdown files (default: all in the materials dir)"
    )
    cmd["lecture"].add_argument("--model", help="Claude model (default: the plugin's lecture_model)")
    cmd["lecture"].add_argument("--force", action="store_true", help="regenerate existing transcripts")

    cmd["tts"].add_argument(
        "files", nargs="*", type=Path, help="lecture transcripts (default: all in the lectures dir)"
    )
    cmd["tts"].add_argument("--voice", help="Speechify voice (default: the plugin's tts_voice)")
    cmd["tts"].add_argument("--rps", type=float, help="requests per second (default: 20, the Starter plan; Free: 1)")
    cmd["tts"].add_argument("--concurrency", type=int, help="concurrent requests (default: 15; Free: 3)")
    cmd["tts"].add_argument("--force", action="store_true", help="regenerate existing MP3s")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    cfg = config.load(args.config, args.plugin, args.input, args.out)

    if args.command == "materials":
        from . import materials

        if cfg.input is None:
            raise SystemExit(f"no input directory: pass --input or set input in {config.CONFIG_NAME}")
        materials.run(cfg, args.lectures, args.dry_run, args.vision, args.model)
    elif args.command == "lecture":
        from slidestolectures import lecture

        lecture.run(cfg.plugin, markdown_files(args.files, cfg.materials), cfg.lectures, args.model, args.force)
    else:
        try:
            from slidestolectures import tts
        except ImportError:
            raise SystemExit("tts needs the Speechify SDK: install coursesitetolectures[tts]") from None

        options = {k: v for k, v in (("rps", args.rps), ("concurrency", args.concurrency)) if v is not None}
        tts.run(
            markdown_files(args.files, cfg.lectures),
            cfg.audio,
            args.voice or cfg.plugin.tts_voice,
            args.force,
            **options,
        )
