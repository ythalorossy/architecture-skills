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
    """Re-running the analyzer after the code changed keeps the model and reports drift."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_new_store_in_the_code_is_drift_and_the_model_is_kept(self):
        repo = self.tmp / "repo"
        shutil.copytree(BOOKSHOP, repo)
        out = self.tmp / "out"
        out.mkdir()
        shutil.copy(BOOKSHOP / "c4-model.json", out / "c4-model.json")
        run_analyzer(repo, out)
        model_before = (out / "c4-model.json").read_bytes()

        # The code gains a Redis cache the model doesn't know about.
        (repo / "api" / "bookshop" / "cache.py").write_text("import redis\nclient = redis.Redis()\n", encoding="utf-8")
        _, summary = run_analyzer(repo, out)

        self.assertEqual((out / "c4-model.json").read_bytes(), model_before, "the analyzer must never rewrite the model")
        self.assertEqual(summary["c4"]["model_status"], "drift")
        self.assertTrue(any("db-redis" in d["message"] for d in summary["c4"]["drift"]), summary["c4"]["drift"])
        report = (out / "ArchitectureReport.md").read_text(encoding="utf-8")
        self.assertIn("### Unreviewed facts", report)
        # Drift still draws the model: the System Context and the key flow are there.
        self.assertTrue((out / "c4-context.mmd").exists())
        self.assertTrue((out / "c4-flow-place-order.mmd").exists())


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
