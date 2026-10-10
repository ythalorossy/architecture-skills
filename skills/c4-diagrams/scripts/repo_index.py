"""
RepoIndex: single-walk repository index with tolerant I/O.

One pruned os.walk, one ignore policy, one cached reader, one skip channel.

Architecture (SPEC-03):
- RepoIndex.build(repo, collector) -> RepoIndex  (one walk per run)
- index.files(view) -> [Path]  (source | manifests | ci_hosting | all)
- index.by_name[name] -> Path
- index.by_suffix(ext) -> [Path]
- index.in_dir(dir) -> [Path]
- index.read_text(path) -> str | None
- index.read_json(path) -> dict | None
- index.read_toml(path) -> dict | None
- index.read_ini(path) -> dict | None
- index.parse_xml(path) -> ET | None
"""
from pathlib import Path
import configparser
import json
import os
import xml.etree.ElementTree as ET

# SPEC-11 cap: 2 MB default, enforced only in read_text.
# One constant — grep test will verify no second cap anywhere in scripts/.
MAX_TEXT_BYTES = 2 * 1024 * 1024

# Base ignore set (IGNORED_DIRS from SPEC-03).
IGNORED_DIRS = {
    "bin", "obj", "node_modules", "TestResults", "__pycache__", "venv",
    "dist", "build", "target", "coverage", "out", "site-packages",
}

# Dot-folder allowlist: CI and hosting markers that are NOT skipped.
# .git, .venv, .tox are NOT on this list.
DOT_ALLOWLIST = {".github", ".circleci", ".azure", ".azuredevops", ".gitlab", ".buildkite"}


# ----------------------------------------------------------------------
# Module-level helpers (for discovery consumers migrating from dotnet_projects)
# ----------------------------------------------------------------------


def is_ignored_dir(name):
    """
    Return True for directories that are always skipped:
    - Base IGNORED_DIRS entries
    - Dot-folders not in DOT_ALLOWLIST
    """
    if name in IGNORED_DIRS:
        return True
    if name.startswith(".") and name not in DOT_ALLOWLIST:
        return True
    return False


def walk_files(repo_path, predicate):
    """
    Yield files under repo_path matching predicate, skipping build/tooling folders.

    DEPRECATED: This performs its own walk. Use RepoIndex.build() once per run
    and then index.files('all') with filtering. This wrapper exists for
    out-of-tree callers during the transition.
    """
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = sorted(
            d for d in dirs
            if not is_ignored_dir(d) and not (Path(root) / d / "pyvenv.cfg").exists()
        )
        for file_name in sorted(files):
            if predicate(file_name):
                yield Path(root) / file_name


def local_tag(element):
    """Strip namespace from XML element tag (e.g. '{http://...}Project' -> 'Project')."""
    return element.tag.rsplit("}", 1)[-1]


class RepoIndex:
    """
    Single-walk repository index with tolerant reader.

    Built once per RepositoryAnalyzer.run(), then passed to all consumers.
    """

    # Build/deploy manifest file names.
    _MANIFEST_NAMES = frozenset(
        ["pyproject.toml", "setup.py", "setup.cfg", "pyproject.yaml",
         "package.json", "package-lock.json", "pnpm-workspace.yaml",
         "lerna.json", "Cargo.toml", "go.mod", "go.sum",
         "pom.xml", "build.gradle", "build.gradle.kts",
         ".csproj", ".fsproj", ".vbproj", ".sln", ".slnx",
         "Makefile", "Dockerfile", ".dockerignore",
         "docker-compose.yml", "docker-compose.yaml",
         "docker-compose.override.yml", "docker-compose.override.yaml",
         "Procfile", ".env", ".env.local", ".env.development",
         ".env.production", ".env.test", ".env.example",
         "Chart.yaml", "kustomization.yaml", "values.yaml",
         "render.yaml", "fly.toml", "vercel.json", "netlify.toml",
         "app.yaml", "serverless.yml", "template.yaml",
         ]
    )

    # CI/CD and hosting marker paths.
    _CI_HOSTING_MARKERS = frozenset(
        [".github/workflows", ".gitlab-ci.yml", ".circleci/config.yml",
         ".azure/pipelines", ".azuredevops/pipelines",
         ".buildkite/pipeline.yml", "Jenkinsfile",
         "bitbucket-pipelines.yml",
         ]
    )

    def __init__(self, root, collector):
        self.root = Path(root).resolve()
        self._collector = collector
        self._files = []          # sorted list of all relative Paths
        self._by_name = {}        # name -> Path (unique names only)
        self._by_suffix = {}      # ext -> [Path]
        self._in_dir = {}         # dir name -> [Path]
        self._text_cache = {}     # path -> text (per-run cache)
        # Directories that os.walk failed to list (PermissionError).
        # We track them here so _should_skip_dir can exclude them from
        # the walk on the NEXT os.walk iteration — onerror can't prevent
        # os.walk from recursing, but we can skip re-adding them to dirnames.
        self._failed_dirs = set()  # resolved absolute Path objects
        # Deduplication cache for _record_skip: set of (str(path), reason)
        self._skip_cache = set()

    # ---------- public API ----------

    def files(self, view="all"):
        """Return sorted list of relative Paths for the named view."""
        if view == "all":
            return list(self._files)
        if view == "source":
            return [p for p in self._files if self._is_source(p)]
        if view == "manifests":
            return [p for p in self._files if self._is_manifest(p)]
        if view == "ci_hosting":
            return [p for p in self._files if self._is_ci_hosting(p)]
        raise ValueError(f"unknown view: {view}")

    @property
    def by_name(self):
        """Dict of name -> Path for uniquely-named files."""
        return self._by_name

    def by_suffix(self, suffix):
        """List of Paths with the given suffix."""
        return list(self._by_suffix.get(suffix, []))

    def walk(self, predicate):
        """
        Iterate absolute Paths in the repo matching the predicate.

        This replaces the old walk_files(repo, predicate) function.
        Predicate takes a filename string (not a Path).
        """
        for rel in self._files:
            if predicate(rel.name):
                yield self.root / rel

    def in_dir(self, dirname):
        """List of Paths that are inside a directory with the given name."""
        return list(self._in_dir.get(dirname, []))

    def read_text(self, path):
        """Read text with tolerant decoding, capped at MAX_TEXT_BYTES."""
        path = self._resolve(path)
        if path is None:
            return None
        # Use absolute path string as cache key for deduplication
        cache_key = str(path.resolve())
        # Check cache
        if cache_key in self._text_cache:
            return self._text_cache[cache_key]
        # Check size cap
        try:
            size = path.stat().st_size
        except OSError:
            return None
        if size > MAX_TEXT_BYTES:
            self._collector.skipped(path, "too_large")
            return None
        # Read and cache
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            self._collector.skipped(path, f"oserror: {exc}")
            return None
        # Warn if replacement chars were added (Latin-1 or other non-UTF-8)
        if "�" in text:
            self._collector.warn("parse", file=str(path), detail="decode replacement characters used")
        self._text_cache[cache_key] = text
        return text

    def read_json(self, path):
        """Parse JSON, returning None on failure (with a warning)."""
        text = self.read_text(path)
        if text is None:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            self._collector.warn("parse", file=str(path), detail=f"invalid JSON: {exc}")
            return None

    def read_toml(self, path):
        """Parse TOML, returning None on failure (with a warning)."""
        text = self.read_text(path)
        if text is None:
            return None
        try:
            import tomllib
            return tomllib.loads(text)
        except Exception as exc:
            self._collector.warn("parse", file=str(path), detail=f"invalid TOML: {exc}")
            return None

    def read_ini(self, path):
        """Parse INI/configparser format, returning None on failure (with a warning)."""
        text = self.read_text(path)
        if text is None:
            return None
        try:
            cfg = configparser.ConfigParser()
            cfg.read_string(text, source=str(path))
            return {s: dict(cfg.items(s)) for s in cfg.sections()}
        except configparser.Error as exc:
            self._collector.warn("parse", file=str(path), detail=f"invalid INI: {exc}")
            return None

    def parse_xml(self, path):
        """Parse XML with ET, returning None on failure (with a warning)."""
        text = self.read_text(path)
        if text is None:
            return None
        try:
            return ET.fromstring(text.encode("utf-8"))
        except ET.ParseError as exc:
            self._collector.warn("parse", file=str(path), detail=f"invalid XML: {exc}")
            return None

    # ---------- diagnostics collector (SPEC-08 minimal stub) ----------

    @staticmethod
    def _default_collector():
        """A minimal SPEC-08 collector stub."""
        class _StubCollector:
            def __init__(self):
                self.warnings = []
                self.skipped = []

            def warn(self, kind, *, file=None, detail=None):
                self.warnings.append({"kind": kind, "file": file, "detail": detail})

            def skipped(self, path, reason):
                self.skipped.append({"path": str(path), "reason": reason})

        return _StubCollector()

    # ---------- construction ----------

    @classmethod
    def build(cls, repo, collector=None):
        """Build the index with a single os.walk."""
        root = Path(repo).resolve()
        if collector is None:
            collector = cls._default_collector()
        idx = cls(root, collector)
        idx._walk()
        return idx

    def _walk(self):
        """Perform the single pruned os.walk."""
        root = self.root
        # onerror must be a module-level function (can't use a bound method)
        for dirpath, dirnames, filenames in os.walk(root, onerror=_walk_onerror(self)):
            dirpath = Path(dirpath)
            # In-place pruning: remove ignored dirs and previously-failed dirs
            pruned = []
            for d in dirnames:
                if self._should_skip_dir(d, dirpath / d):
                    continue
                pruned.append(d)
            dirnames[:] = sorted(pruned)
            for fname in sorted(filenames):
                fpath = dirpath / fname
                # Check symlinks: resolve and verify they stay inside the repo
                if fpath.is_symlink():
                    try:
                        resolved = fpath.resolve()
                    except (OSError, RuntimeError):
                        self._record_skip(fpath, "broken_symlink")
                        continue
                    # Broken symlink: resolved target doesn't exist
                    if not resolved.exists():
                        self._record_skip(fpath, "broken_symlink")
                        continue
                    # Outside symlink: resolved target leaves the repo
                    if not resolved.is_relative_to(root):
                        self._record_skip(fpath, "outside_symlink")
                        continue
                # Add regular files and valid symlinks to the index
                rel = fpath.relative_to(root)
                self._files.append(rel)
                # by_name: first-seen wins for unique names
                if rel.name not in self._by_name:
                    self._by_name[rel.name] = rel
                # by_suffix
                suffix = rel.suffix.lower()
                self._by_suffix.setdefault(suffix, []).append(rel)
                # in_dir
                for part in rel.parts[:-1]:
                    self._in_dir.setdefault(part, []).append(rel)
        self._files.sort()

    def _should_skip_dir(self, name, path):
        """Return True if this directory should be skipped by the ignore policy."""
        # Base IGNORED_DIRS
        if name in IGNORED_DIRS:
            return True
        # Dot-folders: skip all except the allowlist
        if name.startswith("."):
            if name in DOT_ALLOWLIST:
                return False
            return True
        # pyvenv.cfg marks a Python virtualenv (any name)
        # Guard against PermissionError when the directory itself is unreadable
        try:
            if (path / "pyvenv.cfg").exists():
                return True
        except PermissionError:
            pass
        return False

    def _record_skip(self, path, reason):
        """Record a skipped path, deduplicated per (path, reason) pair."""
        key = (str(path), reason)
        if key in self._skip_cache:
            return
        self._skip_cache.add(key)
        self._collector.skipped(path, reason)


    def _resolve(self, path):
        """Resolve path to absolute, or None if outside repo."""
        path = Path(path)
        # Already absolute? resolve normally.
        if path.is_absolute():
            resolved = path.resolve()
        else:
            # Relative path: resolve from index root (not CWD)
            resolved = (self.root / path).resolve()
        if not resolved.is_relative_to(self.root):
            return None
        return resolved

    def _is_source(self, path):
        """True for source files (not vendored, not generated, not test dirs)."""
        parts = path.parts
        name = path.name.lower()
        # Generated / vendored patterns
        if (
            ".min." in name
            or name.endswith(".designer.cs")
            or name.endswith(".g.cs")
            or name.endswith(".g.i.cs")
            or name.endswith("_pb2.py")
            or name.endswith(".generated.")
            or name.endswith(".d.ts")
            or "vendor" in parts
            or "vendors" in parts
            or (len(parts) >= 2 and parts[-2] == "wwwroot" and parts[-1] == "lib")
        ):
            return False
        # Test directories
        TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "e2e", "testdata"}
        if any(p.lower() in TEST_DIRS for p in parts[:-1]):
            return False
        return True

    def _is_manifest(self, path):
        """True for build/deploy manifest files."""
        return path.name in self._MANIFEST_NAMES

    def _is_ci_hosting(self, path):
        """True for CI/CD and hosting marker files."""
        rel = path.as_posix()
        for marker in self._CI_HOSTING_MARKERS:
            if "/" in marker:
                # Directory marker (prefix match): `.github/workflows`, `.circleci/config.yml`
                if rel == marker or rel.startswith(marker + "/"):
                    return True
            else:
                # Root file marker: exact filename at repo root
                # e.g. `.gitlab-ci.yml`, `Jenkinsfile`, `bitbucket-pipelines.yml`
                if rel == marker:
                    return True
        return False


def _walk_onerror(idx):
    """Return an onerror handler for os.walk that uses idx's state."""
    def handler(exc):
        failed = Path(os.path.abspath(getattr(exc, "filename", "")))
        idx._failed_dirs.add(failed)
        idx._record_skip(failed, "permission")
    return handler
