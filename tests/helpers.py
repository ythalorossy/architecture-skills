import copy
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "c4-diagrams"
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))


ABS_PATH_PLACEHOLDER = "<abs-path>"
MASK_PLACEHOLDER = "<masked>"

# Keys whose values are always volatile, mapped to the placeholder that
# should replace the value. ``repository_root`` is the relative path the
# analyzer computes from the output tmpdir back to the fixture; on Linux
# and macOS it bakes in the user's home (``../../home/<user>/...``), on
# Windows same-drive it is a clean ``../../../...`` relative path, and on
# Windows different-drive it is the absolute repo path (``as_posix``).
# All three flavours are environment-specific, so mask by name.
_MASK_BY_NAME = {
    "run_id": MASK_PLACEHOLDER,
    "Generated On": MASK_PLACEHOLDER,
    "repository_root": ABS_PATH_PLACEHOLDER,
}
_MASK_BY_SUBSTRING = ("timestamp",)

# Substrings that prove a string carries an absolute-path component even
# when the string itself starts with a relative prefix. Only the home-like
# patterns: a drive-letter pattern would misfire on URL schemes such as
# ``postgresql://host/db`` (the ``l:/`` substring), and the by-name
# ``repository_root`` mask plus the start-of-string absolute-path prefix
# already cover the real cases.
_EMBEDDED_ABS_PATH = re.compile(
    r"(/home/|/Users/|/private/|/var/folders/|/root/)"
)

# Recognised absolute-path prefixes: POSIX (``/``) or any Windows drive
# letter (``C:\``, ``D:/``, ...). Applied at the start of the string only,
# so a URL scheme is never mistaken for a path.
_ABS_PATH_PREFIX = re.compile(r"^(/|[A-Za-z]:[/\\])")


def write(root, files, crlf=False):
    """Write {relative path: text} under root and return the paths in order."""
    paths = []
    for relative, text in files.items():
        path = Path(root) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
        paths.append(path)
    return paths


def line_of(text, needle):
    """1-based number of the first line containing needle."""
    return next(number for number, line in enumerate(text.splitlines(), 1) if needle in line)


def _mask_key(key):
    """Return the placeholder for a masked-by-name key, or None to recurse."""
    if key in _MASK_BY_NAME:
        return _MASK_BY_NAME[key]
    if any(sub in key for sub in _MASK_BY_SUBSTRING):
        return MASK_PLACEHOLDER
    return None


def _mask_value(value):
    """Recursively mask volatile fields inside a parsed JSON-like structure."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            placeholder = _mask_key(key)
            if placeholder is not None:
                result[key] = placeholder
            else:
                result[key] = _mask_value(item)
        return result
    if isinstance(value, list):
        return [_mask_value(item) for item in value]
    if isinstance(value, str):
        if _ABS_PATH_PREFIX.match(value) or _EMBEDDED_ABS_PATH.search(value):
            return ABS_PATH_PLACEHOLDER
    return value


def mask_volatile(obj):
    """Return a deep-copied JSON structure with volatile fields replaced.

    Recurses into dicts and lists. By-name, replaces the values of keys
    ``run_id``, ``Generated On`` and ``repository_root``, plus any key
    containing ``timestamp``. By-value, replaces any string that looks like
    an absolute filesystem path (POSIX ``/...`` or Windows ``<drive>:\\...``
    / ``<drive>:/...``) and any string that embeds an absolute-path
    component (``/home/``, ``/Users/``, ``/private/``, ``/var/folders/``,
    ``/root/``, or any drive prefix). The intent is to keep golden-file
    comparisons stable: ``summary["output_folder"]`` and
    ``facts["repository_root"]`` are the two fields that actually vary
    today; the by-name ``run_id`` / ``Generated On`` masks stay correct
    for free when SPEC-09 lands.
    """
    return _mask_value(copy.deepcopy(obj))


def run_analyzer(fixture, tmp, *, no_svg=True, timestamp=False, strict=False):
    """Run the analyzer in ``fixture``; write outputs under ``tmp``.

    Uses the public ``RepositoryAnalyzer.run()`` entry point. ``no_svg`` is on
    by default so AC1 (no Node.js / no network) holds without mocking.

    Returns the ``(facts, summary)`` pair as parsed JSON dicts, read off disk
    so the values are byte-identical to what the CLI wrote.
    """
    from scripts.analyze_repository import RepositoryAnalyzer

    analyzer = RepositoryAnalyzer(str(fixture), str(tmp), no_svg=no_svg, timestamp=timestamp, strict=strict)
    analyzer.run()

    output = Path(tmp)
    facts = json.loads((output / "c4-facts.json").read_text(encoding="utf-8"))
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    return facts, summary
