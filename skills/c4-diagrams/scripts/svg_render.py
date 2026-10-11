"""
Bounded, diagnosable SVG rendering pipeline for mermaid-cli (SPEC-05).

Each render returns a Result:
    Result(stem, status, message, seconds)

status is one of:
    ok           — SVG written
    missing-tool — neither mmdc nor npx found
    timeout      — process killed after timeout
    syntax-error — mmdc parse error
    tool-error   — mmdc non-zero exit (non-parse)
    skipped      — circuit breaker tripped before this stem

Public entry point:
    render(stems, output_dir, *, svg_flag=True, env_disabled=False)
        -> list[Result]
"""

from __future__ import annotations

import json
import os
import platform
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import List, NamedTuple, Sequence, Tuple

# Pinned mermaid-cli version — bumped deliberately per SPEC-19
MERMAID_CLI_VERSION = "10.9.1"

# Timeouts (seconds); overridable via env
_TIMEOUT_BASE = int(os.environ.get("C4_SVG_TIMEOUT_BASE", "30"))
_TIMEOUT_PER_DIAGRAM = int(os.environ.get("C4_SVG_TIMEOUT_PER_DIAGRAM", "15"))
_TIMEOUT_INSTALL = int(os.environ.get("C4_SVG_TIMEOUT_INSTALL", "120"))


class Result(NamedTuple):
    """Structured result for one diagram render."""
    stem: str
    status: str      # ok | missing-tool | timeout | syntax-error | tool-error | skipped
    message: str     # human-readable cause or first stderr line
    seconds: float   # wall-clock seconds consumed


# ---------------------------------------------------------------------------
# Mermaid config (no embedded web fonts per SPEC-05)
# ---------------------------------------------------------------------------

_MERMAID_CONFIG = {
    "htmlLabels": False,
    "markdownAutoWrap": False,
    "flowchart": {"htmlLabels": False, "wrappingWidth": 1000},
}


def _write_config() -> Path:
    """Write the mermaid config to a temp file; caller must unlink it."""
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump(_MERMAID_CONFIG, fh)
    return Path(path)


# ---------------------------------------------------------------------------
# Renderer resolution
# ---------------------------------------------------------------------------

def _resolve() -> Tuple[str, List[str]]:
    """
    Return (kind, command).

    kind is 'mmdc', 'npx', or 'missing'.
    command is the full command to run (without -i/-o/-c/-b).
    """
    import shutil

    mmdc = shutil.which("mmdc")
    if mmdc:
        return "mmdc", [mmdc]

    npx = shutil.which("npx")
    if npx:
        return "npx", [npx, "-y", f"@mermaid-js/mermaid-cli@{MERMAID_CLI_VERSION}"]

    return "missing", []


# ---------------------------------------------------------------------------
# Status classification
# ---------------------------------------------------------------------------

def _classify(stderr: str, returncode: int) -> Tuple[str, str]:
    """Return (status, message) from mmdc exit code and stderr."""
    if returncode == 0:
        return "ok", ""

    # Strip ANSI escape codes
    clean = stderr.replace("\x1b[", "")
    lines = [l for l in clean.strip().splitlines() if l]
    first = lines[0] if lines else f"exited with code {returncode}"

    # Parse errors
    lower = clean.lower()
    parse_keywords = ("parse error", "syntax error", "error on line",
                      "unexpected token", "failed to parse")
    if any(kw in lower for kw in parse_keywords):
        return "syntax-error", first

    return "tool-error", first


# ---------------------------------------------------------------------------
# Process group kill
# ---------------------------------------------------------------------------

def _kill_tree(pid: int) -> None:
    """Kill the entire process tree rooted at pid (platform-appropriate)."""
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
        except (ProcessLookupError, TypeError):
            pass


# ---------------------------------------------------------------------------
# Per-diagram renderer
# ---------------------------------------------------------------------------

def _render_one(
    cmd: List[str],
    mmd_path: Path,
    output_svg: Path,
    timeout: float,
    offline: bool = True,
) -> Tuple[int, str, str]:
    """
    Render one diagram with the given timeout.

    Returns (returncode, stdout, stderr).
    returncode -1 means timeout, -2 means failed to start.
    """
    env = os.environ.copy()
    if offline:
        env["npm_config_offline"] = "true"
    else:
        env.pop("npm_config_offline", None)

    config = _write_config()
    args = list(cmd) + [
        "-i", str(mmd_path),
        "-o", str(output_svg),
        "-c", str(config),
        "-b", "white",
    ]

    kw: dict = {
        "args": args,
        "env": env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
    }

    if platform.system() == "Windows":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True

    proc: subprocess.Popen | None = None
    try:
        proc = subprocess.Popen(**kw)   # type: ignore[arg-type]
        stdout, stderr = proc.communicate(timeout=timeout)
        return proc.returncode, stdout or "", stderr or ""
    except subprocess.TimeoutExpired:
        if proc and proc.pid is not None:
            _kill_tree(proc.pid)
        try:
            proc.kill()
        except Exception:
            pass
        return -1, "", "timed out"
    except OSError:
        return -2, "", "failed to start"
    finally:
        if proc:
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
        config.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Batch renderer: all diagrams in one invocation
# ---------------------------------------------------------------------------

def _render_batch(
    cmd: List[str],
    stems_mmd: List[Tuple[str, Path]],
    output_dir: Path,
    timeout: float,
    offline: bool = True,
) -> Tuple[int, str, str, List[Tuple[str, str]]]:
    """
    Render all diagrams in one batch invocation.

    Writes one temp .mmd with %%=~=~stem=~=~ markers separating blocks.
    mmdc writes <stem>.svg files to output_dir.

    Returns (returncode, stdout, stderr, stem_results).
    stem_results: [(stem, status), ...] where status is 'ok', 'timeout', etc.
    """
    if not stems_mmd:
        return 0, "", "", []

    # Write combined markdown with stem markers
    tmp_mmd_fd, tmp_mmd_path = tempfile.mkstemp(suffix=".mmd")
    try:
        with os.fdopen(tmp_mmd_fd, "w", encoding="utf-8") as fh:
            for stem, mmd_path in stems_mmd:
                content = mmd_path.read_text(encoding="utf-8")
                fh.write(f"%%=~=~{stem}=~=~%\n")
                fh.write("```mermaid\n")
                fh.write(content)
                fh.write("\n```\n\n")

        env = os.environ.copy()
        if offline:
            env["npm_config_offline"] = "true"
        else:
            env.pop("npm_config_offline", None)

        config = _write_config()
        args = list(cmd) + [
            "-i", tmp_mmd_path,
            "-o", str(output_dir),
            "-c", str(config),
            "-b", "white",
        ]

        kw: dict = {
            "args": args,
            "env": env,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
        }

        if platform.system() == "Windows":
            kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True

        proc: subprocess.Popen | None = None
        try:
            proc = subprocess.Popen(**kw)   # type: ignore[arg-type]
            stdout, stderr = proc.communicate(timeout=timeout)
            returncode = proc.returncode
        except subprocess.TimeoutExpired:
            if proc and proc.pid is not None:
                _kill_tree(proc.pid)
            try:
                proc.kill()
            except Exception:
                pass
            returncode = -1
            stdout, stderr = "", "timed out"
        except OSError:
            returncode = -2
            stdout, stderr = "", "failed to start"
        finally:
            if proc:
                try:
                    proc.wait(timeout=2)
                except Exception:
                    pass
            config.unlink(missing_ok=True)

        # Classify each stem's result
        stem_results: List[Tuple[str, str]] = []
        for stem, _ in stems_mmd:
            svg_path = output_dir / f"{stem}.svg"
            if svg_path.is_file():
                stem_results.append((stem, "ok"))
            elif returncode == -1:
                stem_results.append((stem, "timeout"))
            elif returncode == -2:
                stem_results.append((stem, "tool-error"))
            else:
                status, _ = _classify(stderr, returncode)
                stem_results.append((stem, status))

        return returncode, stdout, stderr, stem_results

    finally:
        Path(tmp_mmd_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def render(
    stems: Sequence[Tuple[str, Path]],
    output_dir: Path,
    *,
    svg_flag: bool = True,
    env_disabled: bool = False,
) -> List[Result]:
    """
    Render diagrams to SVG using batch mode with per-diagram fallback.

    Strategy:
    1. Batch: all diagrams in one temp .mmd with stem markers
    2. Run once with timeout = base + per_diagram * N
    3. If batch fails OR any SVG missing → per-diagram fallback
    4. Circuit breaker: after first missing-tool/timeout, skip remaining

    Args:
        stems:        sequence of (stem, mmd_path) pairs
        output_dir:   directory to write *.svg files
        svg_flag:     if False, skip all rendering
        env_disabled: if True, skip all rendering (same as svg_flag=False)

    Returns:
        list of Result, one per stem in input order
    """
    if not svg_flag or env_disabled:
        return [Result(stem, "skipped", "rendering disabled", 0.0) for stem, _ in stems]

    stems_list: List[Tuple[str, Path]] = list(stems)
    if not stems_list:
        return []

    output_dir.mkdir(parents=True, exist_ok=True)

    kind, cmd = _resolve()
    if kind == "missing":
        return [Result(stem, "missing-tool",
                       "neither mmdc nor npx found on PATH", 0.0)
                for stem, _ in stems_list]

    # --- Batch attempt: all diagrams in one invocation ---
    batch_timeout = _TIMEOUT_BASE + _TIMEOUT_PER_DIAGRAM * len(stems_list)
    t0 = time.monotonic()

    returncode, stdout, stderr, stem_results = _render_batch(
        cmd, stems_list, output_dir, batch_timeout, offline=True,
    )
    elapsed = time.monotonic() - t0

    # Check for ENOTCACHED → retry online once
    enotcached = any(
        token in stderr for token in ("ENOTCACHED", "ENOTFOUND", "ERR!")
    )
    if enotcached and returncode != 0:
        t0 = time.monotonic()
        returncode, stdout, stderr, stem_results = _render_batch(
            cmd, stems_list, output_dir, batch_timeout, offline=False,
        )
        elapsed = time.monotonic() - t0

    # Check if batch succeeded: all SVGs exist
    all_ok = all(status == "ok" for _, status in stem_results)

    if returncode == 0 and all_ok:
        # Batch succeeded
        results: List[Result] = []
        for stem, _ in stems_list:
            results.append(Result(stem, "ok", "", elapsed / len(stems_list)))
        return results

    # --- Batch failed or some SVGs missing: per-diagram fallback ---
    results = []
    skip = False

    for stem, mmd_path in stems_list:
        if skip:
            results.append(Result(stem, "skipped", "circuit breaker tripped", 0.0))
            continue

        output_svg = output_dir / f"{stem}.svg"
        t0 = time.monotonic()

        returncode, stdout, stderr = _render_one(
            cmd, mmd_path, output_svg, _TIMEOUT_PER_DIAGRAM, offline=True,
        )
        elapsed = time.monotonic() - t0

        # ENOTCACHED → retry online
        enotcached = any(
            token in stderr for token in ("ENOTCACHED", "ENOTFOUND", "ERR!")
        )
        if enotcached and returncode != 0:
            returncode, stdout, stderr = _render_one(
                cmd, mmd_path, output_svg, _TIMEOUT_INSTALL, offline=False,
            )
            elapsed = time.monotonic() - t0

        if returncode == -1:
            results.append(Result(stem, "timeout", "timed out", elapsed))
            skip = True
        elif returncode == -2:
            results.append(Result(stem, "tool-error", "failed to start", elapsed))
            skip = True
        elif returncode == 0:
            results.append(Result(stem, "ok", "", elapsed))
        else:
            status, msg = _classify(stderr, returncode)
            results.append(Result(stem, status, msg, elapsed))
            if status in ("missing-tool", "timeout"):
                skip = True

    return results
