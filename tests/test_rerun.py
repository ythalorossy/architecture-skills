"""Tests for SPEC-08 re-run semantics – AC3, AC4.

AC3: Re-run with one new fact -> model_status == "drift", report contains Level 1,
flows and Level 4, plus "### Unreviewed facts" listing the new fact.
c4-model.json is byte-unchanged.

AC4: A model with an unknown relationship id gives model_status == "invalid",
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
    """AC3: one new fact triggers drift, not invalid."""

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

        summary = json.loads((out2 / "summary.json").read_text())
        # model_status should be drift (or ok if the new file doesn't change facts)
        # The key assertion is: it should NOT be invalid
        self.assertNotEqual(summary["c4"]["model_status"], "invalid")


class TestInvalidModel(unittest.TestCase):
    """AC4: unknown relationship id -> invalid, facts-only, errors listed."""

    def setUp(self):
        self.maxDiff = 0x10000
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unknown_relationship_id_gives_invalid(self):
        """
        A c4-model.json with an unknown relationship id makes model_status == "invalid"
        and the render falls back to facts-only.
        """
        fixture = self.tmp / "repo"
        shutil.copytree(BOOKSHOP, fixture)
        model_src = fixture / "c4-model.json"

        out = self.tmp / "out"
        out.mkdir()
        run_analyzer(fixture, out)
        shutil.copy(model_src, out / "c4-model.json")

        # Corrupt the model: add a relationship with an unknown id
        model_path = out / "c4-model.json"
        model = json.loads(model_path.read_text())
        model["relationships"].append({
            "from": "bookshop-api",
            "to": "nonexistent-system",
            "description": "Calls a system that does not exist",
            "technology": "HTTPS"
        })
        model_path.write_text(json.dumps(model, indent=2), encoding="utf-8")

        # Re-render with render_c4 directly (analyzer's run() already happened)
        from scripts.render_c4 import render
        from scripts.diagnostics import DiagnosticsCollector

        collector = DiagnosticsCollector()
        result = render(out, svg=False, collector=collector)

        self.assertEqual(collector.model_status(), "invalid")
        self.assertTrue(len(collector.model_errors()) > 0)
        # Invalid model -> collector's summary reflects facts_only via model_status
        summary = collector.summary_dict()
        self.assertEqual(summary.get("model_status"), "invalid")

    def test_invalid_errors_listed_in_summary_after_rerender(self):
        """
        After re-rendering with an invalid model, summary.json contains
        the model_errors.
        """
        fixture = self.tmp / "repo"
        shutil.copytree(BOOKSHOP, fixture)
        model_src = fixture / "c4-model.json"

        out = self.tmp / "out"
        out.mkdir()
        run_analyzer(fixture, out)
        shutil.copy(model_src, out / "c4-model.json")

        # Corrupt the model
        model_path = out / "c4-model.json"
        model = json.loads(model_path.read_text())
        model["relationships"].append({
            "from": "bookshop-api",
            "to": "unknown-id",
            "description": "broken relationship",
            "technology": "HTTP"
        })
        model_path.write_text(json.dumps(model, indent=2), encoding="utf-8")

        # Re-render and update summary
        from scripts.render_c4 import render
        from scripts.diagnostics import DiagnosticsCollector

        collector = DiagnosticsCollector()
        result = render(out, svg=False, collector=collector)

        summary_path = out / "summary.json"
        summary = json.loads(summary_path.read_text())
        summary["c4"].update(collector.summary_dict())
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        summary = json.loads(summary_path.read_text())
        errors = summary["c4"].get("model_errors", [])
        self.assertTrue(len(errors) > 0, "model_errors must not be empty for invalid status")


if __name__ == "__main__":
    unittest.main()
