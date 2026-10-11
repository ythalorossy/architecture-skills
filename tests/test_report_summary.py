"""
The agent's own analysis lands in ArchitectureReport.md.

c4-model.json may carry a `summary` (overview, findings, recommendations).
render_c4 writes it into the report, right after the Executive Summary, so
the architect's narrative is kept with the diagrams instead of only in the
chat where the skill ran.
"""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from helpers import run_analyzer

from scripts import render_c4
from scripts.model_check import check_structure

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "repos" / "bookshop"

SUMMARY = {
    "overview": "Bookshop is a React web app in front of a FastAPI service.",
    "findings": ["Orders are written in the same request that charges the card (`api/bookshop/orders/service.py`)."],
    "recommendations": ["Record the charge before writing the order, so a failed insert can be refunded."],
}


class ReportSummaryTest(unittest.TestCase):
    def render(self, model):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        with contextlib.redirect_stdout(io.StringIO()):
            run_analyzer(FIXTURE, tmp)
            if model is not None:
                (Path(tmp) / "c4-model.json").write_text(json.dumps(model), encoding="utf-8")
            result = render_c4.render(tmp, svg=False)
        return result, Path(tmp)

    def model(self, **summary):
        model = json.loads((FIXTURE / "c4-model.json").read_text(encoding="utf-8"))
        model["summary"] = summary or copy.deepcopy(SUMMARY)
        return model

    def test_summary_is_written_after_the_executive_summary(self):
        result, out = self.render(self.model())
        self.assertEqual(result["status"], "ok", result)
        report = (out / "ArchitectureReport.md").read_text(encoding="utf-8")
        executive = report.index("## Executive Summary")
        overview = report.index("## Architecture overview")
        diagrams = report.index("## Architecture (C4 model)")
        self.assertLess(executive, overview)
        self.assertLess(overview, diagrams)
        section = report[overview:diagrams]
        self.assertIn(SUMMARY["overview"], section)
        self.assertIn("### Findings\n\n- Orders are written", section)
        self.assertIn("### Recommendations\n\n- Record the charge", section)

    def test_rerender_keeps_one_summary(self):
        _, out = self.render(self.model())
        with contextlib.redirect_stdout(io.StringIO()):
            render_c4.render(str(out), svg=False)
        report = (out / "ArchitectureReport.md").read_text(encoding="utf-8")
        self.assertEqual(report.count("## Architecture overview"), 1)

    def test_parts_are_optional(self):
        _, out = self.render(self.model(overview="Only an overview."))
        report = (out / "ArchitectureReport.md").read_text(encoding="utf-8")
        self.assertIn("## Architecture overview\n\nOnly an overview.", report)
        self.assertNotIn("### Findings", report)

    def test_no_summary_without_a_model(self):
        _, out = self.render(None)
        self.assertNotIn("## Architecture overview", (out / "ArchitectureReport.md").read_text(encoding="utf-8"))

    def test_wrong_types_are_invalid_with_a_json_path(self):
        model = self.model(findings="one long string")
        errors = check_structure(model).errors
        self.assertIn("c4-model.json:summary.findings: expected a list of strings, got str", errors)
        model = self.model(overview=["a", "b"])
        self.assertIn("c4-model.json:summary.overview: expected a string, got list", check_structure(model).errors)
        model = json.loads((FIXTURE / "c4-model.json").read_text(encoding="utf-8"))
        model["summary"] = "text"
        self.assertIn("c4-model.json:summary: expected an object, got str", check_structure(model).errors)

    def test_misspelled_summary_key_suggests_the_right_one(self):
        result, _ = self.render(self.model(overview="x", finding=["y"]))
        self.assertIn("summary: unknown key 'finding' (did you mean 'findings'?); it is ignored", result["warnings"])


if __name__ == "__main__":
    unittest.main()
