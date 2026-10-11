"""
Failure modes: unreadable, oddly encoded or outside-pointing files.

These tests verify that the analyzer degrades gracefully: it exits 0 with a
warning naming the offending path, instead of crashing or silently ignoring the
problem.

The mode-000 directory and the outside-pointing symlink are built at runtime
inside `tempfile.TemporaryDirectory()` — they are NEVER committed to the
repository. Committing a mode-000 directory or an outside-symlink would break
Windows checkouts in CI (git stores only the executable bit, and an
outside-symlink fails on Windows outright).
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
ANALYZE = REPO / "skills" / "c4-diagrams" / "scripts" / "analyze_repository.py"


def _run_analyzer(repo, out):
    """Run the analyzer on `repo` with output to `out` (no SVG)."""
    return subprocess.run(
        [sys.executable, str(ANALYZE), str(repo), "--output", str(out), "--no-svg"],
        capture_output=True,
        text=True,
    )


class FailureModesTest(unittest.TestCase):
    """A non-UTF-8 setup.cfg, a mode-000 folder and an outside symlink don't stop the run."""

    def test_non_utf8_setup_cfg_does_not_abort(self):
        """A non-UTF-8 setup.cfg must be skipped with a warning,
        not abort the whole run. The analyzer exits 0 with status: degraded
        and a warning naming setup.cfg."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            # A Python project so setup.cfg is parsed.
            (repo / "pkg").mkdir()
            (repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
            # Non-UTF-8 bytes mid-file — invalid start byte 0xff.
            (repo / "setup.cfg").write_bytes(b"[metadata]\nname = b\xff\xfenomer\n")
            out = Path(tmp) / "out"

            proc = _run_analyzer(repo, out)
            combined = proc.stdout + proc.stderr

            self.assertEqual(
                proc.returncode, 0,
                f"analyzer must exit 0 when only setup.cfg is bad; "
                f"got {proc.returncode}\nstderr: {proc.stderr}",
            )
            self.assertIn(
                "setup.cfg", combined,
                f"a warning must name setup.cfg; got:\n{combined}",
            )

    @unittest.skipUnless(os.name == "posix", "POSIX-only: chmod 000 directory")
    def test_unreadable_dir_is_skipped(self):
        """A mode-000 subdirectory must be skipped with a warning,
        not raise through the analyzer. The analyzer exits 0 with status: degraded
        and a warning naming the directory."""

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            unreadable = repo / "no_access"
            unreadable.mkdir()
            # The detector tries to read files inside, so seed with one.
            (unreadable / "pyvenv.cfg").write_text("", encoding="utf-8")
            os.chmod(unreadable, 0)
            out = Path(tmp) / "out"

            try:
                proc = _run_analyzer(repo, out)
                combined = proc.stdout + proc.stderr
                self.assertEqual(
                    proc.returncode, 0,
                    f"analyzer must exit 0 when a subdir is mode 000; "
                    f"got {proc.returncode}\nstderr: {proc.stderr}",
                )
                self.assertIn(
                    "no_access", combined,
                    f"a warning must name no_access; got:\n{combined}",
                )
            finally:
                os.chmod(unreadable, 0o755)

    @unittest.skipUnless(os.name == "posix", "POSIX-only: symlinks")
    def test_outside_symlink_is_skipped(self):
        """A symlink pointing outside the repo must be skipped with
        a warning naming the symlink path. The analyzer exits 0 with
        status: degraded."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            outside = Path(tmp) / "outside"
            outside.mkdir()
            (outside / "leak.py").write_text("y = 2\n", encoding="utf-8")
            link = repo / "leak"
            link.symlink_to(outside)
            out = Path(tmp) / "out"

            proc = _run_analyzer(repo, out)
            combined = proc.stdout + proc.stderr

            self.assertEqual(
                proc.returncode, 0,
                f"analyzer must exit 0; got {proc.returncode}\n"
                f"stderr: {proc.stderr}",
            )
            self.assertIn(
                "leak", combined,
                f"a warning must name the symlink path 'leak'; "
                f"got:\n{combined}",
            )


if __name__ == "__main__":
    unittest.main()
