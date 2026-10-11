"""Load coursesitetolectures.toml and the plugin it names.

    plugin = "my_plugin:MyPlugin"   # module:Class, path/to/file.py[:Class], or omit for the defaults
    input = "course"                # directory of course materials
    output = "out"                  # base directory for everything generated

    [output_dirs]                   # optional: override individual output directories
    materials = "out/materials"     # each lecture's source material, as Markdown
    lectures = "out/lectures"       # lecture transcripts
    audio = "out/audio"             # narrated MP3s

    [settings]                      # plugin attributes, e.g.
    course = "MIT 6.006 Introduction to Algorithms"
    unnumbered = "separate"

Relative paths are resolved against the directory holding the config file.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from slidestolectures.config import load_plugin

from . import ocw
from .plugin import CoursePlugin

CONFIG_NAME = "coursesitetolectures.toml"
OUTPUT_DIRS = {"materials": "materials", "lectures": "lectures", "audio": "audio"}


@dataclass
class Config:
    plugin: CoursePlugin
    input: Path | None
    output: Path
    materials: Path
    lectures: Path
    audio: Path


def load(config_path=None, plugin_spec=None, input_dir=None, output_dir=None):
    """Read the config file (if any), with command-line values taking precedence."""
    if config_path is None and Path(CONFIG_NAME).exists():
        config_path = Path(CONFIG_NAME)
    data, base = {}, Path.cwd()
    if config_path is not None:
        config_path = Path(config_path)
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        base = config_path.resolve().parent
    known = {"plugin", "input", "output", "output_dirs", "settings"}
    if unknown := set(data) - known:
        raise SystemExit(f"{config_path}: unknown key(s) {', '.join(sorted(unknown))}")

    spec = plugin_spec or data.get("plugin")
    plugin = load_plugin(spec, base if plugin_spec is None else Path.cwd()) if spec else CoursePlugin()
    if not isinstance(plugin, CoursePlugin):
        raise SystemExit(f"plugin {spec!r}: must subclass coursesitetolectures.CoursePlugin")
    for key, value in data.get("settings", {}).items():
        if key.startswith("_") or not hasattr(plugin, key) or callable(getattr(plugin, key)):
            raise SystemExit(f"{config_path}: unknown setting {key!r}")
        setattr(plugin, key, value)

    def resolve(value, relative_to):
        return value if value is None else (relative_to / Path(value).expanduser())

    input_dir = resolve(input_dir, Path.cwd()) or resolve(data.get("input"), base)
    if plugin.course is None and input_dir is not None and ocw.is_export(input_dir):
        plugin.course = ocw.course_title(input_dir)
    output = resolve(output_dir, Path.cwd()) or resolve(data.get("output", "out"), base)
    dirs = data.get("output_dirs", {})
    if unknown := set(dirs) - set(OUTPUT_DIRS):
        raise SystemExit(f"{config_path}: unknown output_dirs key(s) {', '.join(sorted(unknown))}")
    paths = {
        key: (output / default if output_dir is not None or key not in dirs else resolve(dirs[key], base))
        for key, default in OUTPUT_DIRS.items()
    }
    return Config(plugin=plugin, input=input_dir, output=output, **paths)
