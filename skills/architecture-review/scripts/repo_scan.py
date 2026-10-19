"""Read a repository's text files once, so every detector shares one walk.

`list_files(repo)` is what the repository holds: in a git work tree, the
tracked files plus untracked ones git does not ignore (so build output such as
`.next/` or `bin/` never reaches a detector); elsewhere, a walk that skips
dependency, build and VCS folders. `text_files(repo)` returns the source,
config, Dockerfile and compose files among them, each a `TextFile` with its
repo-relative POSIX path and its text. Both are capped (file size and file
count) so a huge repository cannot stall the run.
"""
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env", ".tox", ".mypy_cache",
    ".pytest_cache", "dist", "build", "target", "bin", "obj", "vendor", ".idea", ".vscode",
    ".next", ".nuxt", ".svelte-kit", ".turbo", ".vercel", ".output", ".gradle", ".terraform", "coverage",
    "architecture-docs",
}
SOURCE_SUFFIXES = (
    ".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".java", ".kt", ".go", ".cs", ".fs", ".vb", ".rb", ".php",
)
CONFIG_SUFFIXES = (
    ".yml", ".yaml", ".toml", ".json", ".properties", ".cfg", ".ini", ".conf", ".env", ".xml", ".prisma", ".config",
)
CONFIG_NAME_PREFIXES = (
    "dockerfile", "docker-compose", "compose.", ".env", ".npmrc", ".yarnrc", ".pypirc", ".netrc",
)
# Generated or vendored files whose keys look like settings but are not.
IGNORED_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "composer.lock", "poetry.lock"}
TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "testdata", "fixtures", "e2e"}
MAX_BYTES = 1_000_000
MAX_FILES = 20_000


@dataclass(frozen=True)
class TextFile:
    rel: str
    text: str

    @property
    def is_source(self):
        return self.rel.endswith(SOURCE_SUFFIXES)

    @property
    def is_config(self):
        return not self.is_source

    @property
    def is_test(self):
        parts = self.rel.lower().split("/")
        name = parts[-1]
        return (
            any(part in TEST_DIRS for part in parts[:-1])
            or name.startswith("test_")
            or name.endswith(("_test.go", "_test.py"))
            or ".test." in name
            or ".spec." in name
        )


def _wanted(rel):
    name = rel.rsplit("/", 1)[-1].lower()
    if name in IGNORED_NAMES:
        return False
    return name.endswith(SOURCE_SUFFIXES + CONFIG_SUFFIXES) or name.startswith(CONFIG_NAME_PREFIXES)


def _skipped(rel):
    return any(part in SKIP_DIRS for part in rel.split("/")[:-1])


def _git_files(repo):
    """Tracked plus untracked-but-not-ignored files, relative to `repo`; None outside a git work tree."""
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return sorted({p for p in done.stdout.split("\0") if p})


def _walked_files(repo):
    found = []
    for folder, dirs, names in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        found += [(Path(folder) / n).relative_to(repo).as_posix() for n in sorted(names)]
    return found


def list_files(repo):
    """Every file the repository holds, as sorted repo-relative POSIX paths."""
    repo = Path(repo)
    files = _git_files(repo)
    if files is None:
        files = _walked_files(repo)
    return [rel for rel in files if not _skipped(rel) and (repo / rel).is_file()]


def text_files(repo):
    """Every wanted text file in `repo`, sorted by path, capped at MAX_FILES."""
    repo = Path(repo)
    found = []
    for rel in list_files(repo):
        if not _wanted(rel):
            continue
        path = repo / rel
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        found.append(TextFile(rel, text))
        if len(found) >= MAX_FILES:
            break
    return found


def line_of(text, offset):
    """1-based line number of a character offset in `text`."""
    return text.count("\n", 0, offset) + 1


def directory_names(repo):
    """Lowercase names of every folder that holds a file of the repository."""
    names = set()
    for rel in list_files(repo):
        names.update(part.lower() for part in rel.split("/")[:-1])
    return names
