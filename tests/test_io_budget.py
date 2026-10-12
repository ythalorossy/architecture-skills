"""
I/O budget of one analyzer run: the repository is walked once, each
package.json is read once, and discovery is never served from a stale cache.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import REPO_ROOT, SKILL  # noqa: F401  -- sets up sys.path so `scripts` is importable
from scripts.analyze_repository import RepositoryAnalyzer


class TestSingleWalkBudget(unittest.TestCase):
    """exactly one os.walk per run."""

    def test_single_os_walk_per_run(self):
        """RepositoryAnalyzer.run performs exactly one os.walk call."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = REPO_ROOT / "tests" / "fixtures" / "repos" / "python_dist"
            output = Path(tmp) / "out"
            original_walk = os.walk
            call_count = [0]

            def counting_walk(top, *args, **kwargs):
                # Only walks of the repository count. shutil.rmtree walks the
                # staging folder on Windows, which is not repository I/O.
                if Path(top) == fixture:
                    call_count[0] += 1
                return original_walk(top, *args, **kwargs)

            with mock.patch.object(os, "walk", counting_walk):
                analyzer = RepositoryAnalyzer(str(fixture), str(output), no_svg=True)
                analyzer.run()

            self.assertEqual(
                call_count[0], 1,
                f"Expected exactly 1 os.walk call; got {call_count[0]}",
            )


class TestReadOnceBudget(unittest.TestCase):
    """each file is read at most once per run."""

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


class TestNoStaleCache(unittest.TestCase):
    """discover_all returns fresh results after fixture change."""

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
