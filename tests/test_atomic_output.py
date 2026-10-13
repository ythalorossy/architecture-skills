"""The output folder is never left holding half of one run and half of another.

A re-run writes every artifact into a sibling staging folder and moves the
files in only once the whole run succeeded. A crash in the middle therefore
leaves the previous run's folder exactly as it was, and leaves no staging
folder behind.
"""
import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import run_analyzer

from scripts.analyze_repository import RepositoryAnalyzer

FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures" / "repos"
BOOKSHOP = FIXTURES_ROOT / "bookshop"


def _snapshot(folder):
    return {p.name: p.read_bytes() for p in sorted(Path(folder).iterdir()) if p.is_file()}


class TestAtomicOutput(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = self.tmp / "repo"
        shutil.copytree(BOOKSHOP, self.repo)
        self.out = self.tmp / "architecture-docs" / "repo"
        self.out.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _crashing_rerun(self):
        """Re-run over a changed repository, crashing after the report is built."""
        (self.repo / "api" / "bookshop" / "cache.py").write_text(
            "import redis\nclient = redis.Redis()\n", encoding="utf-8"
        )
        analyzer = RepositoryAnalyzer(str(self.repo), str(self.out), no_svg=True)
        with mock.patch.object(RepositoryAnalyzer, "_generate_c4", side_effect=RuntimeError("boom")):
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError):
                    analyzer.run()

    def test_a_crash_leaves_the_previous_run_untouched(self):
        with contextlib.redirect_stdout(io.StringIO()):
            run_analyzer(self.repo, self.out)
        before = _snapshot(self.out)

        self._crashing_rerun()

        self.assertEqual(_snapshot(self.out), before)

    def test_a_crash_leaves_no_staging_folder_behind(self):
        with contextlib.redirect_stdout(io.StringIO()):
            run_analyzer(self.repo, self.out)

        self._crashing_rerun()

        self.assertEqual([p.name for p in self.out.parent.iterdir()], ["repo"])

    def test_a_crash_on_a_first_run_leaves_the_folder_empty(self):
        self._crashing_rerun()

        self.assertEqual(_snapshot(self.out), {})

    def test_an_artifact_of_a_previous_run_that_is_gone_is_removed(self):
        """A diagram the new run does not produce must not survive the promote."""
        with contextlib.redirect_stdout(io.StringIO()):
            run_analyzer(self.repo, self.out)
        stale = self.out / "c4-component-bookshop-gone.mmd"
        stale.write_text("stale\n", encoding="utf-8")

        with contextlib.redirect_stdout(io.StringIO()):
            run_analyzer(self.repo, self.out)

        self.assertFalse(stale.exists())

    def test_the_model_the_user_wrote_is_left_alone(self):
        shutil.copy(BOOKSHOP / "c4-model.json", self.out / "c4-model.json")
        model_before = (self.out / "c4-model.json").read_bytes()

        with contextlib.redirect_stdout(io.StringIO()):
            _, summary = run_analyzer(self.repo, self.out)

        self.assertEqual((self.out / "c4-model.json").read_bytes(), model_before)
        # The model was read from the staging folder, so it still applies.
        self.assertEqual(summary["c4"]["model"], "c4-model.json")
        self.assertTrue((self.out / "c4-context.mmd").is_file())


if __name__ == "__main__":
    unittest.main()
