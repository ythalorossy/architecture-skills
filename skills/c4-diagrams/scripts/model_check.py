"""
Loading and structural checks for c4-model.json.

`ValidationResult` is the typed result object that replaces the ad-hoc
`{"errors", "warnings"}` dict. `status` is derived: errors -> "invalid",
else drift -> "drift", else "ok". `load_model` reads the file, catches
`JSONDecodeError`, names the line and column, and rejects a non-object top
level. `check_structure` is added in Task 2.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    drift: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    model: dict | None = None  # the parsed object (None for invalid loads)

    @property
    def status(self) -> str:
        if self.errors:
            return "invalid"
        if self.drift:
            return "drift"
        return "ok"


def _extract_excerpt(text: str, lineno: int, max_lines: int = 2) -> str:
    """Return the offending line and the next one as a short excerpt."""
    lines = text.splitlines() or [text]
    if lineno < 1 or lineno > len(lines):
        return lines[0][:80] if lines else ""
    snippet = lines[lineno - 1 : lineno - 1 + max_lines]
    return " | ".join(snippet)[:120]


def _find_trailing_comma(text: str) -> tuple[int, int] | None:
    """Return (line, column) of the last trailing comma in `text`, or None.

    A trailing comma is one that sits between a value and a closing bracket
    or brace: `,]` or `,}` (with optional whitespace between them), or `,`
    followed by EOF inside an array/object. This is the common mistake the
    stdlib parser surfaces only at EOF — we report the offending line.
    """
    lines = text.splitlines()
    last: tuple[int, int] | None = None
    for line_index, raw_line in enumerate(lines, 1):
        stripped = raw_line.rstrip()
        if not stripped.endswith(","):
            continue
        # Skip lines that look like they end with a comma inside a string is
        # impossible at the trailing position; we only care about the line
        # trailing position. A trailing comma is followed (after the comma)
        # by closing bracket/brace or by EOF.
        remainder = stripped[:-1].rstrip()
        if not remainder:
            continue
        if remainder.endswith("[") or remainder.endswith("{"):
            # `,[` or `,{` — a leading-comma mistake, not a trailing one.
            continue
        # Column is the position right after the trailing comma.
        column = len(stripped) + 1  # 1-based
        last = (line_index, column)
    # If the parser error happens at EOF and the LAST line of the file ends
    # in a comma right before a closing bracket, prefer that.
    if last and lines and lines[-1].rstrip().endswith(","):
        return last
    return last


def load_model(path: Path) -> ValidationResult:
    """Read c4-model.json without raising.

    Returns a ValidationResult. On JSON syntax errors the lineno/colno are
    converted into an invalid-tier message of the form
    `c4-model.json: line L, column C: <parser message> — <line excerpt>`.
    For trailing-comma errors the stdlib parser reports EOF; we surface the
    offending comma's position instead so the agent can fix it. A non-object
    top level (list or scalar) is invalid with a positional message that
    names the file.
    """
    path = Path(path)
    label = path.name
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ValidationResult(errors=[f"{label}: cannot read ({exc})"])

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        # Trailing-comma detection: the stdlib parser reports EOF for a
        # comma-after-closing-bracket. Look for the trailing comma and
        # point at it instead.
        trailing = _find_trailing_comma(text)
        if trailing and exc.lineno >= len(text.splitlines()):
            line, column = trailing
            offending_line = text.splitlines()[line - 1] if line <= len(text.splitlines()) else ""
            return ValidationResult(
                errors=[
                    f"{label}: line {line}, column {column}: trailing comma before closing bracket "
                    f"— {offending_line.strip()[:80]}"
                ]
            )
        excerpt = _extract_excerpt(text, exc.lineno)
        suffix = f" — {excerpt}" if excerpt else ""
        return ValidationResult(
            errors=[f"{label}: line {exc.lineno}, column {exc.colno}: {exc.msg}{suffix}"]
        )

    if not isinstance(data, dict):
        return ValidationResult(
            errors=[f"{label}: expected an object at the top level, got {type(data).__name__}"]
        )

    return ValidationResult(model=data)


def _check_list_of_objects(items: Iterable, path: str, errors: list[str]) -> bool:
    """Return True when items is a list of dicts, otherwise emit per-index errors."""
    if not isinstance(items, list):
        errors.append(f"{path}: expected a list, got {type(items).__name__}")
        return False
    ok = True
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(
                f"{path}[{index}]: expected an object, got {type(item).__name__!r}"
            )
            ok = False
    return ok


def _require_str_keys(item: dict, keys: Iterable[str], errors: list[str], path: str) -> None:
    for key in keys:
        if key not in item:
            errors.append(f"{path}: missing required string {key!r}")
            continue
        if not isinstance(item[key], str):
            errors.append(
                f"{path}: field {key!r} must be a string, got {type(item[key]).__name__}"
            )


def check_structure(model: dict) -> ValidationResult:
    """Structural pre-check: return a fresh ValidationResult with `errors`
    appended for every wrong-typed section or element.

    `model` is the parsed dict from `load_model`. `check_structure` does not
    inspect semantic relationships; it only confirms types match
    `c4-model-reference.md`. Later checks (render_c4.validate) can assume well-typed
    input.
    """
    errors: list[str] = []
    label = "c4-model.json"

    system = model.get("system")
    if not isinstance(system, dict):
        errors.append(f"{label}: 'system' must be an object")
    else:
        name = system.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"{label}: 'system.name' must be a non-empty string")

    for section in ("people", "containers", "external_systems", "relationships", "excluded", "flows"):
        value = model.get(section)
        if value is None:
            continue
        if not _check_list_of_objects(value, f"{label}:{section}", errors):
            continue
        for index, item in enumerate(value):
            sub = f"{label}:{section}[{index}]"
            if section in ("people", "containers", "external_systems"):
                _require_str_keys(item, ("id", "name"), errors, sub)
            elif section == "relationships":
                _require_str_keys(item, ("from", "to"), errors, sub)
            elif section == "excluded":
                if "id" not in item:
                    errors.append(f"{sub}: missing required string 'id'")
                elif not isinstance(item["id"], str):
                    errors.append(
                        f"{sub}: field 'id' must be a string, got {type(item['id']).__name__}"
                    )
            elif section == "flows":
                _require_str_keys(item, ("name",), errors, sub)
                steps = item.get("steps")
                step_path = f"{sub}.steps"
                if not isinstance(steps, list):
                    errors.append(
                        f"{step_path}: expected a list, got {type(steps).__name__}"
                    )
                else:
                    for step_index, step in enumerate(steps):
                        if not isinstance(step, dict):
                            errors.append(
                                f"{step_path}[{step_index}]: expected an object, got {type(step).__name__}"
                            )
                            continue
                        _require_str_keys(step, ("from", "to"), errors, f"{step_path}[{step_index}]")

    components = model.get("components")
    if components is not None:
        if not isinstance(components, dict):
            errors.append(
                f"{label}:components: expected a map of maps, got {type(components).__name__}"
            )
        else:
            for container_id, inner in components.items():
                if not isinstance(inner, dict):
                    errors.append(
                        f"{label}:components[{container_id!r}]: expected a map of "
                        f"component descriptions, got {type(inner).__name__}"
                    )

    summary = model.get("summary")
    if summary is not None:
        if not isinstance(summary, dict):
            errors.append(f"{label}:summary: expected an object, got {type(summary).__name__}")
        else:
            overview = summary.get("overview")
            if overview is not None and not isinstance(overview, str):
                errors.append(f"{label}:summary.overview: expected a string, got {type(overview).__name__}")
            for key in ("findings", "recommendations"):
                items = summary.get(key)
                if items is not None and (not isinstance(items, list)
                                          or not all(isinstance(i, str) for i in items)):
                    errors.append(f"{label}:summary.{key}: expected a list of strings, got {type(items).__name__}")

    return ValidationResult(model=model, errors=errors)