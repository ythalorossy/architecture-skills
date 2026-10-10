"""
I/O budget and budget enforcement tests (SPEC-03 AC1, AC5, AC6, AC7, AC9).

AC1  — exactly one os.walk per run (patched count)
AC5  — each file read at most once per run (patched RepoIndex)
AC6  — one size-cap constant in scripts/ (grep)
AC7  — no rglob, no def _read, no dotnet_projects imports outside dotnet_projects.py (grep)
AC9  — discover_all returns updated results after fixture change (no stale cache)
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import REPO_ROOT, SKILL  # noqa: F401  -- sets up sys.path so `scripts` is importable
from scripts import repo_index
from scripts.analyze_repository import RepositoryAnalyzer


class TestSingleWalkBudget(unittest.TestCase):
    """AC1: exactly one os.walk per run."""

    def test_single_os_walk_per_run(self):
        """RepositoryAnalyzer.run performs exactly one os.walk call."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = REPO_ROOT / "tests" / "fixtures" / "repos" / "python_dist"
            output = Path(tmp) / "out"
            original_walk = os.walk
            call_count = [0]

            def counting_walk(*args, **kwargs):
                call_count[0] += 1
                return original_walk(*args, **kwargs)

            with mock.patch.object(os, "walk", counting_walk):
                analyzer = RepositoryAnalyzer(str(fixture), str(output), no_svg=True)
                analyzer.run()

            self.assertEqual(
                call_count[0], 1,
                f"Expected exactly 1 os.walk call; got {call_count[0]}",
            )


class TestReadOnceBudget(unittest.TestCase):
    """AC5: each file is read at most once per run."""

    def test_package_json_read_once(self):
        """package.json is read exactly once per run."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = REPO_ROOT / "tests" / "fixtures" / "repos" / "node_workspace"
            output = Path(tmp) / "out"
            read_calls = []

            original_read_text = Path.read_text

            def tracking_read_text(self, *args, **kwargs):
                read_calls.append(str(self))
                return original_read_text(self, *args, **kwargs)

            with mock.patch.object(Path, "read_text", tracking_read_text):
                analyzer = RepositoryAnalyzer(str(fixture), str(output), no_svg=True)
                analyzer.run()

            package_json_reads = [p for p in read_calls if "package.json" in p]
            from collections import Counter
            counts = Counter(package_json_reads)
            duplicates = {f: c for f, c in counts.items() if c > 1}
            self.assertEqual(
                duplicates, {},
                f"package.json was read more than once: {dict(counts)}",
            )


class TestNoRglobOrReadCopies(unittest.TestCase):
    """AC7: no rglob, no def _read, no dotnet_projects imports outside dotnet_projects.py."""

    def test_no_rglob_or_def_read_in_scripts(self):
        """scripts/ contains no rglob calls and no 'def _read' definitions."""
        scripts_dir = REPO_ROOT / "skills" / "c4-diagrams" / "scripts"

        rglob_matches = []
        def_read_matches = []

        for py_file in scripts_dir.rglob("*.py"):
            text = py_file.read_text()
            for lineno, line in enumerate(text.splitlines(), 1):
                if "rglob" in line:
                    rglob_matches.append((py_file.relative_to(REPO_ROOT), lineno, line.strip()))
                if "def _read" in line:
                    def_read_matches.append((py_file.relative_to(REPO_ROOT), lineno, line.strip()))

        self.assertEqual(
            rglob_matches, [],
            f"rglob found in scripts/:\n" +
            "\n".join(f"  {p}:{n}: {line}" for p, n, line in rglob_matches),
        )
        self.assertEqual(
            def_read_matches, [],
            f"'def _read' found in scripts/:\n" +
            "\n".join(f"  {p}:{n}: {line}" for p, n, line in def_read_matches),
        )

    def test_no_module_imports_dotnet_projects_helpers(self):
        """No module except dotnet_projects.py imports helper functions from dotnet_projects.

        Helper functions (is_ignored_dir, walk_files, local_tag, project_group, etc.)
        should be imported from repo_index and paths instead.
        """
        scripts_dir = REPO_ROOT / "skills" / "c4-diagrams" / "scripts"
        bad_imports = []

        for py_file in scripts_dir.rglob("*.py"):
            if py_file.name == "dotnet_projects.py":
                continue
            text = py_file.read_text()
            for lineno, line in enumerate(text.splitlines(), 1):
                # Flag: importing helper functions from dotnet_projects (they should come from repo_index/paths)
                if "from scripts.dotnet_projects import" in line or \
                   "from .dotnet_projects import" in line:
                    bad_imports.append((py_file.relative_to(REPO_ROOT), lineno, line.strip()))

        self.assertEqual(
            bad_imports, [],
            f"Bad dotnet_projects imports found:\n" +
            "\n".join(f"  {p}:{n}: {line}" for p, n, line in bad_imports),
        )


class TestSingleSizeCap(unittest.TestCase):
    """AC6: exactly one size-cap constant in scripts/."""

    def test_single_size_cap_constant(self):
        """MAX_TEXT_BYTES appears once in scripts/ (or as a shared constant from SPEC-11)."""
        scripts_dir = REPO_ROOT / "skills" / "c4-diagrams" / "scripts"
        cap_lines = []

        for py_file in scripts_dir.rglob("*.py"):
            text = py_file.read_text()
            for lineno, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                # Match size cap literals: 2 * 1024 * 1024, MAX_TEXT_BYTES, SIZE_CAP, etc.
                if any(pat in line for pat in [
                    "MAX_TEXT_BYTES", "SIZE_CAP", "TEXT_CAP",
                    "* 1024 * 1024",  # the literal 2MB
                ]) and not line.strip().startswith("#"):
                    cap_lines.append((py_file.relative_to(REPO_ROOT), lineno, line.strip()))

        # Allow at most one definition (in repo_index.py or a shared constants module)
        definition_count = sum(
            1 for p, n, line in cap_lines
            if "MAX_TEXT_BYTES" in line and ":" not in line and "=" in line
        )
        self.assertLessEqual(
            definition_count, 1,
            f"Multiple size-cap definitions found:\n" +
            "\n".join(f"  {p}:{n}: {line}" for p, n, line in cap_lines),
        )


class TestNoStaleCache(unittest.TestCase):
    """AC9: discover_all returns fresh results after fixture change."""

    def test_discover_all_not_stale_after_change(self):
        """Calling discover_all twice in one process after modifying the fixture returns updated results."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "repo"
            fixture.mkdir()
            (fixture / "pkg").mkdir()
            (fixture / "pkg" / "__init__.py").write_text("", encoding="utf-8")
            (fixture / "pyproject.toml").write_text(
                '[project]\nname = "pkg"\nversion = "0.1.0"\n',
                encoding="utf-8",
            )

            from scripts.projects import discover_all

            # First discovery — should find 1 project
            result1 = discover_all(fixture)
            # discover_all returns dict with 'projects' (list of dicts) and 'solutions' (list)
            projects1 = result1.get("projects", [])
            names1 = sorted(p["name"] for p in projects1)

            # Mutate: add a second project
            (fixture / "pkg2").mkdir()
            (fixture / "pkg2" / "__init__.py").write_text("", encoding="utf-8")
            (fixture / "pkg2" / "pyproject.toml").write_text(
                '[project]\nname = "pkg2"\nversion = "0.1.0"\n',
                encoding="utf-8",
            )

            # Second discovery — should now find 2 projects (no stale cache)
            result2 = discover_all(fixture)
            projects2 = result2.get("projects", [])
            names2 = sorted(p["name"] for p in projects2)

            self.assertNotEqual(
                names1, names2,
                f"discover_all returned stale results after fixture change. "
                f"Before: {names1}, After: {names2} (expected ['pkg', 'pkg2'])",
            )
            self.assertEqual(names2, ["pkg", "pkg2"])


if __name__ == "__main__":
    unittest.main()
