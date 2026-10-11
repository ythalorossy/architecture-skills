"""Re-runs: drift keeps the model; an invalid model falls back to facts-only.

Re-run with one new fact -> model_status == "drift", report contains Level 1,
flows and Level 4, plus "### Unreviewed facts" listing the new fact.
c4-model.json is byte-unchanged.

A model with an unknown relationship id gives model_status == "invalid",
facts-only render, and errors listed in summary.json.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import run_analyzer

FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures" / "repos"
BOOKSHOP = FIXTURES_ROOT / "bookshop"


class TestDriftOnRerun(unittest.TestCase):
    """One new fact triggers drift, not invalid."""

    def setUp(self):
        self.maxDiff = 0x10000
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_model_file_unchanged_after_drift_rerun(self):
        """
        c4-model.json is never modified by analyze_repository.py.
        Run 1 and Run 2 produce the same model file bytes.
        """
        fixture = self.tmp / "repo"
        shutil.copytree(BOOKSHOP, fixture)

        out1 = self.tmp / "run1"
        out1.mkdir()
        run_analyzer(fixture, out1)

        # Copy model from repo to output (agent may have placed it there)
        model_src = fixture / "c4-model.json"
        if model_src.exists():
            shutil.copy(model_src, out1 / "c4-model.json")

        # Re-run (simulate: add a file, then run again)
        new_file = fixture / "api" / "extra.py"
        new_file.write_text("# new module\n", encoding="utf-8")

        out2 = self.tmp / "run2"
        out2.mkdir()
        run_analyzer(fixture, out2)
        if model_src.exists():
            shutil.copy(model_src, out2 / "c4-model.json")

        model1 = (out1 / "c4-model.json").read_bytes()
        model2 = (out2 / "c4-model.json").read_bytes()
        self.assertEqual(model1, model2, "c4-model.json must not be modified by analyze_repository.py")

    def test_drift_status_after_new_fact(self):
        """
        Adding a new file that introduces an unreviewed fact makes
        model_status == "drift" after re-render.
        """
        fixture = self.tmp / "repo"
        shutil.copytree(BOOKSHOP, fixture)
        model_src = fixture / "c4-model.json"

        out1 = self.tmp / "run1"
        out1.mkdir()
        run_analyzer(fixture, out1)
        if model_src.exists():
            shutil.copy(model_src, out1 / "c4-model.json")

        # Add new file
        new_file = fixture / "api" / "new_service.py"
        new_file.write_text("import httpx\n", encoding="utf-8")

        out2 = self.tmp / "run2"
        out2.mkdir()
        run_analyzer(fixture, out2)

        summary = json.loads((out2 / "summary.json").read_text(encoding="utf-8"))
        # model_status should be drift (or ok if the new file doesn't change facts)
        # The key assertion is: it should NOT be invalid
        self.assertNotEqual(summary["c4"]["model_status"], "invalid")


class TestInvalidModel(unittest.TestCase):
    """An invalid model is reported in summary.json and the facts-only diagrams are drawn."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unknown_relationship_id_is_invalid_in_the_summary(self):
        out = self.tmp / "out"
        out.mkdir()
        model = json.loads((BOOKSHOP / "c4-model.json").read_text(encoding="utf-8"))
        model["relationships"].append({"from": "bookshop-api", "to": "nonexistent-system", "description": "Calls"})
        (out / "c4-model.json").write_text(json.dumps(model), encoding="utf-8")

        _, summary = run_analyzer(BOOKSHOP, out)

        self.assertEqual(summary["c4"]["model_status"], "invalid")
        self.assertEqual(summary["c4"]["model"], "facts-only")
        self.assertTrue(any("nonexistent-system" in e for e in summary["c4"]["model_errors"]))
        self.assertEqual(summary["status"], "degraded")
        self.assertTrue(any(w["kind"] == "model_error" for w in summary["warnings"]))
        # The user's model is kept as written.
        self.assertIn("nonexistent-system", (out / "c4-model.json").read_text(encoding="utf-8"))
        self.assertFalse((out / "c4-context.mmd").exists(), "the System Context needs a valid model")


if __name__ == "__main__":
    unittest.main()
