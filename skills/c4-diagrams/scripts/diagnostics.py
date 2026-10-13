"""
Run-scoped diagnostics collector.

Collects warnings and skipped-file events from every detector and script
during one analysis run, deduplicates them, and serialises them for
summary.json.

Kinds
-----
- parse  : a manifest or source file that could not be read
- skipped: a file or path that was skipped (permission, symlink, size)
- render : a diagram or SVG that failed to render
- model  : a model-tier drift (a fact the model does not cover yet)
- model_error : a model-tier error (the model is invalid and was not drawn)

The collector is passed into components that would otherwise print to stderr.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Diagnostic:
    source: str       # module / script name, e.g. "python_projects"
    path: str | None  # repo-relative path, forward-slash, or None
    message: str
    kind: str         # parse | skipped | render | model | model_error

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

    def __init__(self, root=None) -> None:
        self._seen: set[Diagnostic] = set()
        self._list: list[Diagnostic] = []
        self._degraded = False
        # The repository, when known: paths are filed relative to it, the
        # way the user names them. A path outside it is kept as it is.
        self._root = Path(root).resolve() if root is not None else None

    @property
    def degraded(self) -> bool:
        """
        True when something went wrong that the user should look at: a file
        that could not be read or parsed, a diagram that failed to render, or
        an invalid c4-model.json. Drift (facts the model doesn't cover yet)
        is the normal state after the code changes, so it isn't degraded.
        """
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

    def detection(self, source: str, message: str) -> None:
        """Record a gap in what the analyzer could detect (not degraded: nothing failed)."""
        self._add(Diagnostic(source, None, message, "detection"))

    def model_warning(self, source: str, message: str, path: str | None = None) -> None:
        """Record a model-tier hint: a fact the model does not cover yet, or
        something to fix in c4-model.json that still lets it be drawn."""
        self._add(Diagnostic(source, path, message, "model"))

    def model_error(self, source: str, message: str, path: str | None = None) -> None:
        """Record a model-tier error: the model is invalid and is not drawn."""
        self._add(Diagnostic(source, path, message, "model_error"))

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

    def _relative(self, path: str | None) -> str | None:
        """A repository path as the user writes it: relative, forward slashes."""
        if path is None or self._root is None:
            return path
        try:
            candidate = Path(path)
            if not candidate.is_absolute():
                return path
            return candidate.resolve().relative_to(self._root).as_posix()
        except (ValueError, OSError):
            return path

    def _add(self, diagnostic: Diagnostic) -> None:
        diagnostic = Diagnostic(
            diagnostic.source, self._relative(diagnostic.path), diagnostic.message, diagnostic.kind
        )
        if diagnostic not in self._seen:
            self._seen.add(diagnostic)
            self._list.append(diagnostic)
            if diagnostic.kind in ("parse", "skipped", "render", "model_error"):
                self._degraded = True

    # ------------------------------------------------------------------
    # Serialisation for summary.json
    # ------------------------------------------------------------------

    def warnings(self) -> list[dict]:
        """All diagnostics as a list of dicts, for summary.json."""
        return [d.to_dict() for d in self._list]

    def skipped_files(self) -> list[dict]:
        """Skipped-file entries only, for summary.json.

        One entry per file and reason: the same file can be dropped by two
        scanners, and the user is being told about the file, not about
        which module reached it first.
        """
        entries = []
        for d in self._list:
            if d.kind != "skipped":
                continue
            entry = {"path": d.path, "reason": d.message}
            if entry not in entries:
                entries.append(entry)
        return entries
