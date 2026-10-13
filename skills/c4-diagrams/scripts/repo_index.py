"""
RepoIndex: single-walk repository index with tolerant I/O.

One pruned os.walk, one ignore policy, one cached reader, one skip channel.

API:
- RepoIndex.build(repo, collector) -> RepoIndex  (one walk per run)
- RepoIndex.ensure(index, folder)   -> the index passed, or a new one
- index.walk(predicate, under=None)  -> absolute Paths
- index.files()                      -> relative Paths
- index.by_suffix(ext)               -> relative Paths
- index.read_text / read_json / read_ini(path) -> value | None
- read_file_text(path, source)      -> text ("" when unreadable or too large)
- recording_skips(collector)        -> context manager: file the size drops
"""
from contextlib import contextmanager
from pathlib import Path
import configparser
import json
import os

# Files larger than this are not read (generated bundles, data dumps).
MAX_TEXT_BYTES = 2 * 1024 * 1024

# Where read_file_text() files the size drops of the run it is inside.
# The scanners in c4_facts and code_facts read files from module-level
# helpers that have no collector of their own, so collect_facts installs
# one here for the length of the run. One run at a time, single-threaded.
_SKIP_SINK = None

# Text read by read_file_text() during the current run, or None outside one.
# The Level 3 and Level 4 scanners each walk the same source files, so every
# one of them was read three or four times. Scoped to the run so that a
# second analysis in the same process cannot be served a stale file.
_TEXT_CACHE = None
_TEXT_CACHE_BYTES = 0

# The index of the current run, so read_file_text() can answer from text it
# has already read. None outside a run.
_RUN_INDEX = None

# How much of that text to hold. Source files are capped at 2 MB each and a
# repository can have thousands, so the cache stops taking new entries once
# it reaches this and keeps serving the ones it has. Big enough for whole
# repositories in practice, bounded for the ones it is not.
MAX_CACHE_BYTES = 64 * 1024 * 1024


@contextmanager
def recording_skips(collector, index=None):
    """Record what read_file_text() drops, and cache what it reads, for one run.

    Passing the run's index lets the module-level reader answer from text the
    index has already read, instead of the same file arriving twice because
    discovery went through one reader and the scanners through the other.
    """
    global _SKIP_SINK, _TEXT_CACHE, _TEXT_CACHE_BYTES, _RUN_INDEX
    previous, previous_cache = _SKIP_SINK, _TEXT_CACHE
    previous_bytes, previous_index = _TEXT_CACHE_BYTES, _RUN_INDEX
    _SKIP_SINK = collector
    _TEXT_CACHE = {}
    _TEXT_CACHE_BYTES = 0
    _RUN_INDEX = index
    try:
        yield
    finally:
        _SKIP_SINK = previous
        _TEXT_CACHE = previous_cache
        _TEXT_CACHE_BYTES = previous_bytes
        _RUN_INDEX = previous_index


def read_file_text(path, source):
    """Text of a file, or "" when it is unreadable or past MAX_TEXT_BYTES.

    The cap keeps generated bundles and data dumps out of the scanners. A
    file dropped for its size is recorded, so the run can say what it did
    not read. An unreadable or missing one is not: callers probe for files
    that may not be there (a Dockerfile next to a compose service).
    """
    global _TEXT_CACHE_BYTES
    try:
        path = Path(path)
        key = str(path)
        if _TEXT_CACHE is not None and key in _TEXT_CACHE:
            return _TEXT_CACHE[key]
        if _RUN_INDEX is not None:
            already = _RUN_INDEX.cached_text(path)
            if already is not None:
                return already
        if path.stat().st_size > MAX_TEXT_BYTES:
            if _SKIP_SINK is not None:
                _SKIP_SINK.file_skipped(source, str(path), "too_large")
            return ""
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""
    if _TEXT_CACHE is not None and _TEXT_CACHE_BYTES < MAX_CACHE_BYTES:
        _TEXT_CACHE[key] = text
        _TEXT_CACHE_BYTES += len(text)
    return text


# Folders never walked: build output, dependencies, tool caches.
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
    Yield files under repo_path matching predicate, skipping build/tooling
    folders and virtualenvs. For code that has no RepoIndex: Level 4 type
    extraction at render time, and single-folder scans. The analysis itself
    walks once, with RepoIndex.
    """
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = sorted(
            d for d in dirs
            if not is_ignored_dir(d) and not (Path(root) / d / "pyvenv.cfg").exists()
        )
        for file_name in sorted(files):
            if predicate(file_name):
                yield Path(root) / file_name


class RepoIndex:
    """
    Single-walk repository index with tolerant reader.

    Built once per RepositoryAnalyzer.run(), then passed to all consumers.
    """

    def __init__(self, root, collector):
        self.root = Path(root).resolve()
        self._collector = collector
        self._files = []          # sorted list of all relative Paths
        self._by_suffix = {}      # ext -> [Path]
        self._text_cache = {}     # path -> text (per-run cache)
        # Deduplication cache for _record_skip: set of (str(path), reason)
        self._skip_cache = set()

    # ---------- public API ----------

    @property
    def collector(self):
        """The run's diagnostics collector (warn() / skipped() / file_skipped())."""
        return self._collector

    def files(self):
        """Every indexed file, as sorted paths relative to the root."""
        return list(self._files)

    def by_suffix(self, suffix):
        """List of Paths with the given suffix."""
        return list(self._by_suffix.get(suffix, []))

    def walk(self, predicate, under=None):
        """
        Iterate absolute Paths in the repo matching the predicate.

        This replaces the old walk_files(repo, predicate) function.
        Predicate takes a filename string (not a Path).

        `under` limits the walk to files inside that directory (a path inside the
        repository). Without it the whole repository is searched, so a caller that
        means "this module" must pass its directory: a file outside the directory
        is never returned.
        """
        prefix = None
        if under is not None:
            resolved = Path(under).resolve()
            if not resolved.is_relative_to(self.root):
                return
            # String prefixes: Path.is_relative_to per file was the cost of
            # module-by-module walks in large monorepos.
            relative = resolved.relative_to(self.root).as_posix()
            prefix = "" if relative == "." else relative + "/"
        for rel, posix in zip(self._files, self._posix()):
            if prefix and not posix.startswith(prefix):
                continue
            if predicate(rel.name):
                yield self.root / rel

    def _posix(self):
        """Forward-slash strings of the file paths, built once."""
        if getattr(self, "_posix_files", None) is None or len(self._posix_files) != len(self._files):
            self._posix_files = [rel.as_posix() for rel in self._files]
        return self._posix_files

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
            # strerror only: the exception text repeats the absolute path.
            self._collector.skipped(path, f"oserror: {exc.strerror or exc}")
            return None
        # Warn if replacement chars were added (Latin-1 or other non-UTF-8)
        if "�" in text:
            self._collector.warn("parse", file=str(path), detail="decode replacement characters used")
        self._text_cache[cache_key] = text
        return text

    def cached_text(self, path):
        """Text this index has already read for `path`, or None. Never reads."""
        resolved = self._resolve(path)
        return None if resolved is None else self._text_cache.get(str(resolved))

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

    # ---------- diagnostics collector ----------

    @staticmethod
    def _default_collector():
        """Collector for callers that don't pass one (it has warn() and skipped())."""
        from scripts.diagnostics import DiagnosticsCollector
        return DiagnosticsCollector()

    # ---------- construction ----------

    @classmethod
    def ensure(cls, index, folder, collector=None):
        """The index the caller passed, or one built for `folder` when it passed none."""
        return index if index is not None else cls.build(folder, collector)

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
            # In-place pruning: remove ignored dirs, unreadable dirs, and outside-symlink dirs
            pruned = []
            for d in dirnames:
                dpath = dirpath / d
                # Check for directory symlinks pointing outside the repo
                if dpath.is_symlink():
                    try:
                        resolved = dpath.resolve()
                    except (OSError, RuntimeError):
                        self._record_skip(dpath, "broken_symlink")
                        continue
                    if not resolved.is_relative_to(root):
                        self._record_skip(dpath, "outside_symlink")
                        continue
                if self._should_skip_dir(d, dpath):
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
                # by_suffix
                suffix = rel.suffix.lower()
                self._by_suffix.setdefault(suffix, []).append(rel)
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


def _walk_onerror(idx):
    """Return an onerror handler for os.walk that uses idx's state."""
    def handler(exc):
        failed = Path(os.path.abspath(getattr(exc, "filename", "")))
        idx._record_skip(failed, "permission")
    return handler
