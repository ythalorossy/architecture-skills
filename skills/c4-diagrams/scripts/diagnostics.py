"""
Run-scoped diagnostics collector for SPEC-08.

Collects warnings and skipped-file events from every detector and script
during one analysis run, deduplicates them, and serialises them for
summary.json.

Kinds
-----
- parse  : a manifest or source file that could not be read
- skipped: a file or path that was skipped (permission, symlink, size)
- render : a diagram or SVG that failed to render
- model  : a model-tier issue (drift, invalid relationship id)

The collector is passed into components that would otherwise print to stderr.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass
class Diagnostic:
    source: str       # module / script name, e.g. "python_projects"
    path: str | None  # repo-relative path, forward-slash, or None
    message: str
    kind: str         # parse | skipped | render | model

    def to_dict(self) -> dict:
        d = {"source": self.source, "message": self.message, "kind": self.kind}
        if self.path is not None:
            d["path"] = self.path
        return d

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Diagnostic):
            return NotImplemented
        return (
            self.source == other.source
            and self.path == other.path
            and self.message == other.message
            and self.kind == other.kind
        )

    def __hash__(self) -> int:
        return hash((self.source, self.path, self.message, self.kind))


class DiagnosticsCollector:
    """
    Accumulates diagnostics for one run.

    Duplicate diagnostics (same source + path + message + kind) are collapsed
    so that a repeated warning does not multiply the entries in summary.json.
    """

    def __init__(self) -> None:
        self._seen: set[Diagnostic] = set()
        self._list: list[Diagnostic] = []
        self._degraded = False

    @property
    def degraded(self) -> bool:
        """True when at least one diagnostic makes the run degraded."""
        return self._degraded

    # ------------------------------------------------------------------
    # Public API – call these from detectors and scripts
    # ------------------------------------------------------------------

    def parse_error(self, source: str, path: str, message: str) -> None:
        """Record a manifest or source file that could not be parsed."""
        self._add(Diagnostic(source, path, message, "parse"))

    def file_skipped(self, source: str, path: str, reason: str) -> None:
        """Record a file or path that was skipped (permission, symlink, etc.)."""
        self._add(Diagnostic(source, path, reason, "skipped"))

    def render_warning(self, source: str, message: str, path: str | None = None) -> None:
        """Record a render (SVG or diagram) failure."""
        self._add(Diagnostic(source, path, message, "render"))

    def model_warning(self, source: str, message: str, path: str | None = None) -> None:
        """Record a model-tier issue (drift, invalid relationship, etc.)."""
        self._add(Diagnostic(source, path, message, "model"))

    # ------------------------------------------------------------------
    # RepoIndex compatibility (RepoIndex calls skipped(path, reason) directly)
    # ------------------------------------------------------------------

    def skipped(self, path, reason) -> None:
        """RepoIndex compatibility: record a skipped file."""
        self._add(Diagnostic("repo_index", str(path), str(reason), "skipped"))

    def warn(self, kind: str, *, file=None, detail=None) -> None:
        """Generic warn compatible with RepoIndex._default_collector."""
        path = str(file) if file is not None else None
        if kind == "parse":
            self.parse_error("repo_index", path, detail or "")
        elif kind == "render":
            self.render_warning("repo_index", detail or "", path)
        elif kind == "model":
            self.model_warning("repo_index", detail or "", path)
        else:
            self._add(Diagnostic("repo_index", path, detail or "", kind))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _add(self, diagnostic: Diagnostic) -> None:
        if diagnostic not in self._seen:
            self._seen.add(diagnostic)
            self._list.append(diagnostic)
            if diagnostic.kind == "parse":
                self._degraded = True

    # ------------------------------------------------------------------
    # Serialisation for summary.json
    # ------------------------------------------------------------------

    def warnings(self) -> list[dict]:
        """All diagnostics as a list of dicts, for summary.json."""
        return [d.to_dict() for d in self._list]

    def skipped_files(self) -> list[dict]:
        """Skipped-file entries only, for summary.json."""
        return [
            {"path": d.path, "reason": d.message}
            for d in self._list
            if d.kind == "skipped"
        ]

    def model_status(self) -> str:
        """
        One of 'ok' | 'drift' | 'invalid' based on model-tier diagnostics.

        'drift'  – at least one unreviewed fact (new element not in model)
        'invalid' – at least one unknown relationship id or missing element
        'ok'     – no model-tier diagnostics
        """
        kinds = {d.kind for d in self._list}
        if "model" not in kinds:
            return "ok"
        # Heuristic: messages about "unknown" ids or missing elements = invalid.
        # Messages about facts "found in code but not in the model" = drift.
        for d in self._list:
            if d.kind == "model":
                lc = d.message.lower()
                # "was found in the code but is not in the model" -> drift
                if "was found in the code but is not in the model" in lc:
                    continue
                # "unknown" or "not found" about an id/element -> invalid
                if "unknown" in lc or ("not found" in lc and "type" not in lc):
                    return "invalid"
        return "drift"

    def model_errors(self) -> list[str]:
        """Model-tier error messages (invalid only)."""
        if self.model_status() != "invalid":
            return []
        return [d.message for d in self._list if d.kind == "model"]

    def drift(self) -> list[dict]:
        """Drift entries: model-tier diagnostics that are not invalid."""
        if self.model_status() != "drift":
            return []
        return [d.to_dict() for d in self._list if d.kind == "model"]

    def summary_dict(self) -> dict:
        """
        Complete diagnostics dict for the 'c4' section of summary.json.
        """
        status = self.model_status()
        result: dict = {
            "model_status": status,
        }
        if status == "invalid":
            result["model_errors"] = self.model_errors()
        elif status == "drift":
            result["drift"] = self.drift()
        return result
