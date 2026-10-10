"""Tests for SPEC-08 relocatable output – AC5.

AC5: Copying the output folder one level deeper and running render_c4.py <copy>
exits 0. It prints exactly one "repository not found at … pass --repo" warning,
and no "no classes or interfaces found" warning. With --repo <real path>, Level 4 renders.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures" / "repos"
BOOKSHOP = FIXTURES_ROOT / "bookshop"


class TestRelocatableOutput(unittest.TestCase):
    """AC5: output folder can be moved and re-rendered with --repo."""

    def setUp(self):
        self.maxDiff = 0x10000
        self.tmp = Path(tempfile.mkdtemp())

        # Run the analyzer once on bookshop to produce outputs
        from helpers import run_analyzer

        self.fixture = self.tmp / "bookshop_repo"
        shutil.copytree(BOOKSHOP, self.fixture)

        self.out = self.tmp / "output"
        self.out.mkdir()
        run_analyzer(self.fixture, self.out)

        # Copy c4-model.json into the output folder and re-render so Level 4 exists
        model_src = self.fixture / "c4-model.json"
        if model_src.exists():
            shutil.copy(model_src, self.out / "c4-model.json")
            # Re-render to generate Level 4 diagrams
            skill_dir = Path(__file__).resolve().parent.parent / "skills" / "c4-diagrams"
            result = subprocess.run(
                [sys.executable, str(skill_dir / "scripts" / "render_c4.py"), str(self.out)],
                capture_output=True, text=True,
            )
            # If render fails, that's OK - the test will check for Level 4

        # Verify Level 4 exists in the original output
        mmd_files = list(self.out.glob("c4-*.mmd"))
        code_diagrams = [f for f in mmd_files if "code" in f.name]
        self.assertTrue(
            len(code_diagrams) > 0,
            f"Level 4 diagram should exist in original output: {sorted(f.name for f in mmd_files)}"
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_moved_folder_no_repository_warning(self):
        """
        Copy the output folder one level deeper. Re-running render_c4.py
        on the copy prints "repository not found at …" but does NOT print
        "no classes or interfaces found".
        """
        # Move output deeper
        moved_out = self.tmp / "deeper" / "architecture-docs" / "bookshop"
        shutil.copytree(self.out, moved_out)

        skill_dir = Path(__file__).resolve().parent.parent / "skills" / "c4-diagrams"
        script = skill_dir / "scripts" / "render_c4.py"

        result = subprocess.run(
            [sys.executable, str(script), str(moved_out)],
            capture_output=True,
            text=True,
        )

        # Must exit 0 (not fail)
        self.assertEqual(result.returncode, 0, f"render_c4.py should exit 0: {result.stderr}")

        # Must print the "repository not found" warning
        combined = result.stdout + result.stderr
        self.assertIn("repository not found", combined.lower())
        self.assertIn("pass --repo", combined.lower())

        # Must NOT print "no classes or interfaces found"
        self.assertNotIn(
            "no classes or interfaces found",
            combined.lower(),
            "'no classes or interfaces found' should not appear when repo path is wrong"
        )

    def test_repo_override_enables_level4(self):
        """
        With --repo <real path>, Level 4 diagrams are produced even when
        the output folder has been moved.
        """
        moved_out = self.tmp / "deeper" / "architecture-docs" / "bookshop"
        shutil.copytree(self.out, moved_out)

        skill_dir = Path(__file__).resolve().parent.parent / "skills" / "c4-diagrams"
        script = skill_dir / "scripts" / "render_c4.py"

        result = subprocess.run(
            [sys.executable, str(script), str(moved_out), "--repo", str(self.fixture)],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, f"render_c4.py --repo should exit 0: {result.stderr}")

        # Check that Level 4 diagrams were produced
        mmd_files = list(moved_out.glob("c4-*.mmd"))
        code_diagrams = [f for f in mmd_files if "code" in f.name]
        self.assertTrue(
            len(code_diagrams) > 0,
            f"Level 4 diagrams should exist with --repo: {sorted(f.name for f in mmd_files)}"
        )


if __name__ == "__main__":
    unittest.main()
