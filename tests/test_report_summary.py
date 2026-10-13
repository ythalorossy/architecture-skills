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


class ExecutiveSummaryTest(unittest.TestCase):
    """The Executive Summary describes the system when a model describes one."""

    def render(self, model):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        with contextlib.redirect_stdout(io.StringIO()):
            run_analyzer(FIXTURE, tmp)
            if model is not None:
                (Path(tmp) / "c4-model.json").write_text(json.dumps(model), encoding="utf-8")
            render_c4.render(tmp, svg=False)
        return Path(tmp)

    def summary(self, out):
        report = (out / "ArchitectureReport.md").read_text(encoding="utf-8")
        start = report.index("## Executive Summary")
        return report[start:report.index("[//]: # (c4:start)", start)]

    def reference(self):
        return json.loads((FIXTURE / "c4-model.json").read_text(encoding="utf-8"))

    def test_the_model_replaces_the_project_count(self):
        section = self.summary(self.render(self.reference()))
        self.assertIn("Online shop where readers find books and buy them.", section)
        self.assertIn("The model of Bookshop describes 2 containers, 2 data stores, 1 external system, "
                      "1 person, 5 relationships and 1 key flow.", section)
        self.assertNotIn("6 projects", section)
        # The dependency checks still report what they found.
        self.assertIn("no structural concerns", section)

    def test_without_a_model_the_projects_are_described(self):
        section = self.summary(self.render(None))
        self.assertIn("bookshop has 6 projects (6 production, 0 tests) with 4 project references between them.",
                      section)

    def test_the_counts_are_pluralised(self):
        """B-37: 'compose_poly has 1 projects' reached a committed golden."""
        from scripts import generate_docs

        one = generate_docs.generate_report(
            project_name="solo", stacks=["Python"], graph={"app": []},
            scan={"projects": [{"name": "app", "ecosystem": "Python"}]}, groups={}, mermaid="")
        self.assertIn("solo has 1 project (1 production, 0 tests) with 0 project references between them.", one)

        two = generate_docs.generate_report(
            project_name="pair", stacks=["Python"], graph={"app": ["lib"], "lib": []},
            scan={"projects": [{"name": "app", "ecosystem": "Python"},
                               {"name": "lib", "ecosystem": "Python"}]}, groups={}, mermaid="")
        self.assertIn("pair has 2 projects (2 production, 0 tests) with 1 project reference between them.", two)

    def test_rerendering_keeps_one_summary(self):
        out = self.render(self.reference())
        with contextlib.redirect_stdout(io.StringIO()):
            render_c4.render(str(out), svg=False)
        report = (out / "ArchitectureReport.md").read_text(encoding="utf-8")
        self.assertEqual(report.count("The model of Bookshop describes"), 1)
        self.assertEqual(report.count("[//]: # (summary:start)"), 1)

    def test_a_facts_only_render_leaves_the_summary_alone(self):
        out = self.render(self.reference())
        with contextlib.redirect_stdout(io.StringIO()):
            render_c4.render(str(out), facts_only=True, svg=False)
        self.assertIn("The model of Bookshop describes", self.summary(out))


class StrengthsTest(ExecutiveSummaryTest):
    """With a model, a strength is a property of the model, not of the package graph."""

    def strengths(self, out):
        report = (out / "ArchitectureReport.md").read_text(encoding="utf-8")
        start = report.index("### Strengths")
        return report[start:report.index("### Concerns", start)]

    def test_leaf_packages_are_not_strengths_of_a_modelled_system(self):
        section = self.strengths(self.render(self.reference()))
        self.assertNotIn("Projects with no project references", section)
        self.assertNotIn("web/src/api", section)

    def test_the_model_is_what_the_strengths_describe(self):
        section = self.strengths(self.render(self.reference()))
        self.assertIn("Every container says what it is responsible for.", section)
        self.assertIn("Every container and external system points at the code that proves it.", section)
        self.assertIn("1 key flow", section)

    def test_an_undescribed_container_is_not_claimed_as_a_strength(self):
        model = self.reference()
        model["containers"][0].pop("description", None)
        section = self.strengths(self.render(model))
        self.assertNotIn("Every container says what it is responsible for.", section)

    def test_an_unproven_element_is_not_claimed_as_a_strength(self):
        model = self.reference()
        model["containers"][0]["evidence"] = []
        model["containers"][0]["assumption"] = True
        section = self.strengths(self.render(model))
        self.assertNotIn("points at the code that proves it", section)

    def test_the_graph_checks_keep_their_own_line(self):
        section = self.strengths(self.render(self.reference()))
        self.assertIn("No circular project references.", section)

    def test_without_a_model_the_graph_strengths_are_kept(self):
        section = self.strengths(self.render(None))
        self.assertIn("Projects with no project references", section)

    def test_rerendering_keeps_one_strengths_section(self):
        out = self.render(self.reference())
        with contextlib.redirect_stdout(io.StringIO()):
            render_c4.render(str(out), svg=False)
        report = (out / "ArchitectureReport.md").read_text(encoding="utf-8")
        self.assertEqual(report.count("Every container says what it is responsible for."), 1)
        self.assertEqual(report.count("[//]: # (strengths:start)"), 1)


if __name__ == "__main__":
    unittest.main()
