"""
Render Mermaid diagrams to SVG with mermaid-cli, one process per diagram.

Each render returns a Result:
    Result(stem, status, message, seconds)

status is one of:
    ok           — SVG written
    missing-tool — neither mmdc nor npx found
    timeout      — process tree killed after the timeout
    syntax-error — mmdc could not parse the diagram
    tool-error   — mmdc failed for another reason
    skipped      — rendering disabled, or skipped after the renderer
                   itself failed (timeout, could not start)

Public entry point:
    render(stems, output_dir) -> list[Result]
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import signal
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, NamedTuple, Sequence, Tuple

# Exact mermaid-cli version used through npx, so SVGs are the same on every
# machine. Bump it deliberately and check the rendered diagrams when you do.
MERMAID_CLI_VERSION = "12.0.0"

# Seconds; overridable via env. The first npx run may download mermaid-cli
# and a headless Chrome (a few hundred MB), so it gets the install timeout.
_TIMEOUT_PER_DIAGRAM = int(os.environ.get("C4_SVG_TIMEOUT_PER_DIAGRAM", "180"))
_TIMEOUT_INSTALL = int(os.environ.get("C4_SVG_TIMEOUT_INSTALL", "600"))

# Diagrams rendered at the same time (each one starts a headless Chrome).
_WORKERS = 4


class Result(NamedTuple):
    """Outcome of rendering one diagram."""
    stem: str
    status: str      # ok | missing-tool | timeout | syntax-error | tool-error | skipped
    message: str     # human-readable cause, or the first stderr line
    seconds: float   # wall-clock seconds spent


# Plain <text> labels: HTML labels (<foreignObject>) go blank in some viewers
# when the SVG is shown as an <img>. A system font instead of mermaid's
# embedded web font keeps each SVG around 50 KB instead of about 200 KB.
_MERMAID_CONFIG = {
    "htmlLabels": False,
    "markdownAutoWrap": False,
    "fontFamily": "arial,sans-serif",
    "themeVariables": {"fontFamily": "arial,sans-serif"},
    "flowchart": {"htmlLabels": False, "wrappingWidth": 1000},
}


def disabled_by_env() -> bool:
    """C4_SVG=0 (or false/no) turns SVG rendering off, like --no-svg."""
    return os.environ.get("C4_SVG", "1").strip().lower() in ("0", "false", "no")


def _write_config() -> Path:
    """Write the mermaid config to a temp file; the caller unlinks it."""
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump(_MERMAID_CONFIG, fh)
    return Path(path)


def _resolve() -> Tuple[str, List[str]]:
    """
    Return (kind, command) where kind is 'mmdc', 'npx' or 'missing'.

    shutil.which returns the full path, so Windows .cmd shims (mmdc.cmd,
    npx.cmd) start correctly.
    """
    mmdc = shutil.which("mmdc")
    if mmdc:
        return "mmdc", [mmdc]

    npx = shutil.which("npx")
    if npx:
        return "npx", [npx, "-y", f"@mermaid-js/mermaid-cli@{MERMAID_CLI_VERSION}"]

    return "missing", []


def _classify(stderr: str, returncode: int) -> Tuple[str, str]:
    """Return (status, message) from mmdc's exit code and stderr."""
    if returncode == 0:
        return "ok", ""

    lines = [line for line in stderr.strip().splitlines() if line.strip()]
    first = lines[0].strip() if lines else f"exited with code {returncode}"

    lower = stderr.lower()
    parse_keywords = ("parse error", "syntax error", "error on line",
                      "unexpected token", "failed to parse")
    if any(keyword in lower for keyword in parse_keywords):
        return "syntax-error", first

    return "tool-error", first


def _kill_tree(pid: int) -> None:
    """Kill the whole process tree rooted at pid (npx → node → Chrome)."""
    if platform.system() == "Windows":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _render_one(
    cmd: List[str],
    mmd_path: Path,
    output_svg: Path,
    timeout: float,
    offline: bool = True,
) -> Tuple[int, str, str]:
    """
    Render one diagram. Returns (returncode, stdout, stderr), where
    returncode -1 means timed out and -2 means the process could not start.

    offline=True asks npx to use its cache only, so a machine without
    network access fails fast with ENOTCACHED instead of waiting on the
    registry.
    """
    env = os.environ.copy()
    if offline:
        env["npm_config_offline"] = "true"
    else:
        env.pop("npm_config_offline", None)

    config = _write_config()
    kw: dict = {
        "args": list(cmd) + [
            "-i", str(mmd_path),
            "-o", str(output_svg),
            "-c", str(config),
            "-b", "white",
        ],
        "env": env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    # Own process group, so a timeout can kill Chrome along with npx.
    if platform.system() == "Windows":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True

    proc = None
    try:
        proc = subprocess.Popen(**kw)
        stdout, stderr = proc.communicate(timeout=timeout)
        return proc.returncode, stdout or "", stderr or ""
    except subprocess.TimeoutExpired:
        _kill_tree(proc.pid)
        try:
            proc.kill()
            proc.communicate(timeout=5)   # drain and close the pipes
        except Exception:
            pass
        return -1, "", f"timed out after {timeout:g} s"
    except OSError as error:
        return -2, "", f"could not start {cmd[0]}: {error}"
    finally:
        if proc:
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
        config.unlink(missing_ok=True)


def _render_stem(cmd, stem, mmd_path, output_dir, timeout, offline) -> Result:
    """Render one stem and classify the outcome."""
    output_svg = output_dir / f"{stem}.svg"
    start = time.monotonic()
    returncode, _, stderr = _render_one(cmd, mmd_path, output_svg, timeout, offline=offline)

    # Offline npx with an empty cache: install once, online.
    if offline and returncode != 0 and "ENOTCACHED" in stderr:
        returncode, _, stderr = _render_one(cmd, mmd_path, output_svg, _TIMEOUT_INSTALL, offline=False)

    seconds = time.monotonic() - start
    if returncode == -1:
        return Result(stem, "timeout", stderr, seconds)
    if returncode == -2:
        return Result(stem, "tool-error", stderr, seconds)
    status, message = _classify(stderr, returncode)
    if status == "ok" and not output_svg.is_file():
        return Result(stem, "tool-error", "mmdc exited 0 but wrote no SVG", seconds)
    return Result(stem, status, message, seconds)


def render(
    stems: Sequence[Tuple[str, Path]],
    output_dir: Path,
    *,
    svg_flag: bool = True,
    env_disabled: bool = False,
) -> List[Result]:
    """
    Render each (stem, mmd_path) to output_dir/<stem>.svg.

    The first diagram renders alone: with npx it may install mermaid-cli and
    Chrome, and if the renderer cannot start or hangs, the rest are skipped
    instead of each waiting out its own timeout. The others then render in
    parallel. A syntax error in one diagram doesn't stop the others.

    Returns one Result per stem, in input order.
    """
    stems_list = list(stems)
    if not svg_flag or env_disabled:
        return [Result(stem, "skipped", "rendering disabled", 0.0) for stem, _ in stems_list]
    if not stems_list:
        return []

    output_dir.mkdir(parents=True, exist_ok=True)

    kind, cmd = _resolve()
    if kind == "missing":
        return [Result(stem, "missing-tool", "neither mmdc nor npx found on PATH", 0.0)
                for stem, _ in stems_list]

    offline = kind == "npx"
    first_stem, first_mmd = stems_list[0]
    first = _render_stem(cmd, first_stem, first_mmd, output_dir, _TIMEOUT_PER_DIAGRAM, offline)
    results = [first]
    rest = stems_list[1:]

    if first.status == "timeout" or first.message.startswith("could not start"):
        reason = f"skipped: {first.stem} {first.message}"
        return results + [Result(stem, "skipped", reason, 0.0) for stem, _ in rest]

    if rest:
        with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
            results += list(pool.map(
                lambda item: _render_stem(cmd, item[0], item[1], output_dir, _TIMEOUT_PER_DIAGRAM, offline),
                rest,
            ))
    return results
