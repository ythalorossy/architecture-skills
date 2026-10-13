"""
Evidence and assumption marking on flows and flow steps (B-26, SPEC-07).

A flow is the most interpreted part of the model: the containers and stores
come from the code, the order in which they talk to each other comes from the
agent reading it. Until now nothing recorded which steps were traced and which
were guessed, so a sequence diagram of six steps looked equally certain all the
way down. A flow and a step now take `evidence` and `assumption`, the evidence
is checked like any other, and a step nothing backs is drawn with `(?)`.
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

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "repos" / "bookshop"


class FlowEvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            cls.facts, _ = run_analyzer(FIXTURE, tmp)
        cls.reference = json.loads((FIXTURE / "c4-model.json").read_text(encoding="utf-8"))

    def check(self, change):
        model = copy.deepcopy(self.reference)
        change(model)
        return render_c4.validate(model, self.facts, repo=FIXTURE)

    def flows(self, change):
        model = copy.deepcopy(self.reference)
        change(model)
        return {stem: mermaid for stem, _, mermaid, _ in render_c4.flow_diagrams(model, self.facts)}

    # ---------- the contract ----------

    def test_evidence_and_assumption_are_documented_keys(self):
        self.assertIn("evidence", render_c4.FLOW_KEYS)
        self.assertIn("assumption", render_c4.FLOW_KEYS)
        self.assertIn("evidence", render_c4.STEP_KEYS)
        self.assertIn("assumption", render_c4.STEP_KEYS)

    def test_the_reference_model_stays_clean(self):
        result = self.check(lambda m: None)
        self.assertEqual((result.errors, result.drift, result.warnings), ([], [], []))

    def test_a_flow_with_neither_is_a_warning(self):
        def strip(model):
            model["flows"][0].pop("evidence", None)
            for step in model["flows"][0]["steps"]:
                step.pop("evidence", None)
        result = self.check(strip)
        self.assertTrue(
            any("no evidence and not marked as an assumption" in w and "Reader buys a book" in w
                for w in result.warnings),
            result.warnings,
        )

    def test_marking_the_flow_an_assumption_silences_it(self):
        def mark(model):
            flow = model["flows"][0]
            flow.pop("evidence", None)
            flow["assumption"] = True
            for step in flow["steps"]:
                step.pop("evidence", None)
        self.assertEqual(self.check(mark).warnings, [])

    def test_evidence_that_points_at_nothing_is_reported(self):
        result = self.check(lambda m: m["flows"][0]["steps"][0].update({"evidence": ["web/src/nope.tsx:4"]}))
        self.assertTrue(
            any("web/src/nope.tsx:4" in w and "does not exist" in w for w in result.warnings),
            result.warnings,
        )

    def test_a_step_past_the_end_of_a_file_is_reported(self):
        result = self.check(lambda m: m["flows"][0]["steps"][0].update({"evidence": ["web/src/api/client.ts:9000"]}))
        self.assertTrue(
            any("is past the end of the file" in w for w in result.warnings),
            result.warnings,
        )

    def test_an_unknown_key_on_a_step_still_warns(self):
        result = self.check(lambda m: m["flows"][0]["steps"][0].update({"evidenc": ["x"]}))
        self.assertTrue(any("unknown key 'evidenc'" in w for w in result.warnings), result.warnings)

    # ---------- the marker ----------

    def test_an_assumed_step_is_drawn_with_a_question_mark(self):
        def mark(model):
            step = model["flows"][0]["steps"][2]
            step.pop("evidence", None)
            step["assumption"] = True
        drawn = self.flows(mark)["c4-flow-place-order"]
        self.assertIn("Places the order (?)", drawn)
        self.assertNotIn("Clicks Buy on a book (?)", drawn)

    def test_a_step_with_evidence_is_never_marked(self):
        def mark(model):
            step = model["flows"][0]["steps"][2]
            step["assumption"] = True
            step["evidence"] = ["api/bookshop/main.py:16"]
        self.assertNotIn("(?)", self.flows(mark)["c4-flow-place-order"])

    def test_an_assumed_flow_marks_every_step_that_has_no_evidence_of_its_own(self):
        def mark(model):
            flow = model["flows"][0]
            flow["assumption"] = True
            for step in flow["steps"]:
                step.pop("evidence", None)
            flow["steps"][0]["evidence"] = ["api/bookshop/main.py:16"]
        drawn = self.flows(mark)["c4-flow-place-order"]
        self.assertEqual(drawn.count("(?)"), len(self.reference["flows"][0]["steps"]) - 1)

    def test_a_proven_flow_is_drawn_without_markers(self):
        self.assertNotIn("(?)", self.flows(lambda m: None)["c4-flow-place-order"])

    # ---------- the report ----------

    def test_an_assumed_flow_reaches_the_assumptions_list(self):
        model = copy.deepcopy(self.reference)
        model["flows"][0]["assumption"] = True
        items = render_c4._assumptions(model)
        self.assertTrue(any("Reader buys a book" in item for item in items), items)

    def test_an_assumed_step_reaches_the_assumptions_list(self):
        model = copy.deepcopy(self.reference)
        model["flows"][0]["steps"][2].pop("evidence", None)
        model["flows"][0]["steps"][2]["assumption"] = True
        items = render_c4._assumptions(model)
        self.assertTrue(any("Places the order" in item for item in items), items)

    def test_a_proven_flow_is_not_listed(self):
        items = render_c4._assumptions(copy.deepcopy(self.reference))
        self.assertFalse(any("Reader buys a book" in item for item in items), items)


if __name__ == "__main__":
    unittest.main()
