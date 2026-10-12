"""
render_c4.validate() tells the agent what is wrong with c4-model.json and
how to fix it: close-match suggestions for typos, evidence that points at
nothing, fields that are empty or misspelled.

Each test starts from the bookshop reference model, which validates with no
errors, drift or warnings, and introduces one mistake.
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


class ModelHintsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            cls.facts, _ = run_analyzer(FIXTURE, tmp)
        cls.reference = json.loads((FIXTURE / "c4-model.json").read_text(encoding="utf-8"))

    def check(self, change):
        model = copy.deepcopy(self.reference)
        change(model)
        return render_c4.validate(model, self.facts, repo=FIXTURE)

    def container(self, model, element_id):
        return next(c for c in model["containers"] if c["id"] == element_id)

    def test_reference_model_is_clean(self):
        result = self.check(lambda m: None)
        self.assertEqual((result.errors, result.drift, result.warnings), ([], [], []))

    def test_unknown_relationship_id_suggests_the_close_one(self):
        result = self.check(lambda m: m["relationships"][0].update({"to": "bookshop-wb"}))
        self.assertTrue(any("unknown 'to' id 'bookshop-wb' (did you mean 'bookshop-web'?)" in e
                            for e in result.errors), result.errors)

    def test_component_id_as_a_relationship_end_points_at_flows(self):
        result = self.check(lambda m: m["relationships"][1].update({"to": "bookshop.orders"}))
        self.assertTrue(any("unknown 'to' id 'bookshop.orders'" in e and "use a flow step" in e
                            for e in result.errors), result.errors)

    def test_unknown_flow_participant_suggests_the_close_one(self):
        result = self.check(lambda m: m["flows"][0]["steps"][0].update({"to": "bookshop-wb"}))
        self.assertTrue(any("did you mean 'bookshop-web'?" in e for e in result.errors), result.errors)

    def test_typo_in_facts_names_the_cause(self):
        # The real fact then shows up as drift; the warning says why.
        result = self.check(lambda m: self.container(m, "db-postgresql").update({"facts": ["db-postgresq"]}))
        self.assertIn("db-postgresql: facts lists 'db-postgresq', which is not in c4-facts.json "
                      "(did you mean 'db-postgresql'?)", result.warnings)

    def test_evidence_file_that_does_not_exist(self):
        result = self.check(lambda m: m["external_systems"][0].update({"evidence": ["api/bookshop/stripe.py:1"]}))
        self.assertTrue(any("evidence 'api/bookshop/stripe.py:1' does not exist in the repository" in w
                            for w in result.warnings), result.warnings)

    def test_evidence_line_past_the_end_of_the_file(self):
        result = self.check(lambda m: m["external_systems"][0].update({"evidence": ["docker-compose.yml:999"]}))
        self.assertTrue(any("evidence 'docker-compose.yml:999' is past the end of the file" in w
                            for w in result.warnings), result.warnings)

    def test_evidence_with_a_note_and_a_line_range_is_accepted(self):
        result = self.check(lambda m: m["external_systems"][0].update(
            {"evidence": ["docker-compose.yml:1-3 (compose service db)"]}))
        self.assertEqual(result.warnings, [])

    def test_evidence_is_not_checked_without_a_repository(self):
        model = copy.deepcopy(self.reference)
        model["external_systems"][0]["evidence"] = ["nowhere.py"]
        self.assertEqual(render_c4.validate(model, self.facts).warnings, [])

    def test_empty_name_is_invalid(self):
        result = self.check(lambda m: self.container(m, "bookshop-api").update({"name": " "}))
        self.assertTrue(any("containers[" in e and "needs an id and a name" in e for e in result.errors), result.errors)

    def test_misspelled_key_suggests_the_right_one(self):
        def change(model):
            person = model["people"][0]
            person["assumptions"] = person.pop("assumption")
        result = self.check(change)
        self.assertIn("reader: unknown key 'assumptions' (did you mean 'assumption'?); it is ignored", result.warnings)

    def test_unknown_type(self):
        result = self.check(lambda m: self.container(m, "db-postgresql").update({"type": "databse"}))
        self.assertIn("db-postgresql: unknown type 'databse' (did you mean 'database'?); "
                      "use container, database or queue", result.warnings)

    def test_fact_covered_twice(self):
        result = self.check(lambda m: self.container(m, "bookshop-web").update({"facts": ["bookshop-web", "bookshop-api"]}))
        self.assertIn("bookshop-api is covered by both bookshop-api and bookshop-web; it is drawn once, "
                      "as bookshop-api", result.warnings)

    def test_duplicate_relationship_pair(self):
        def change(model):
            model["relationships"].append({"from": "bookshop-web", "to": "bookshop-api",
                                           "description": "Also calls", "technology": "WebSocket"})
        result = self.check(change)
        self.assertIn("bookshop-web -> bookshop-api is listed twice (relationships[1], relationships[5]); "
                      "they are drawn as one arrow", result.warnings)

    def test_excluded_needs_a_reason(self):
        result = self.check(lambda m: m["excluded"][0].pop("reason"))
        self.assertIn("excluded ext-covers-example: give a reason, so readers know why it is left out", result.warnings)

    def test_owned_data_store_filed_as_an_external_system(self):
        def change(model):
            store = self.container(model, "db-postgresql")
            model["containers"].remove(store)
            model["external_systems"].append(store)
        result = self.check(change)
        self.assertIn("db-postgresql: db-postgresql is a data store found in this repository; move it to "
                      "containers with \"type\": \"database\", and add \"external\": true if the system "
                      "does not own it", result.warnings)

    def test_unknown_key_on_a_relationship(self):
        result = self.check(lambda m: m["relationships"][0].update({"technolgy": "HTTPS"}))
        self.assertIn("relationships[0]: unknown key 'technolgy' (did you mean 'technology'?); it is ignored",
                      result.warnings)

    def test_unknown_key_on_a_flow(self):
        result = self.check(lambda m: m["flows"][0].update({"descripton": "x"}))
        self.assertIn("flows[0]: unknown key 'descripton' (did you mean 'description'?); it is ignored",
                      result.warnings)

    def test_unknown_key_on_a_flow_step(self):
        result = self.check(lambda m: m["flows"][0]["steps"][0].update({"notes": "x"}))
        self.assertIn("flows[0].steps[0]: unknown key 'notes' (did you mean 'note'?); it is ignored",
                      result.warnings)

    def test_excluded_unknown_fact(self):
        result = self.check(lambda m: m["excluded"].append({"id": "ext-coverz-example", "reason": "x"}))
        self.assertIn("excluded ext-coverz-example is not in c4-facts.json (did you mean 'ext-covers-example'?)",
                      result.warnings)



class RenderReportsEvidenceTest(unittest.TestCase):
    def test_render_finds_the_repository_and_warns(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            run_analyzer(FIXTURE, tmp)
            model = json.loads((FIXTURE / "c4-model.json").read_text(encoding="utf-8"))
            model["external_systems"][0]["evidence"] = ["api/bookshop/stripe.py:1"]
            (Path(tmp) / "c4-model.json").write_text(json.dumps(model), encoding="utf-8")
            result = render_c4.render(tmp, svg=False)
        self.assertEqual(result["status"], "ok")
        self.assertIn("ext-payments-example: evidence 'api/bookshop/stripe.py:1' does not exist in the repository",
                      result["warnings"])

class ReportAssumptionsTest(unittest.TestCase):
    """Anything unproven is shown as an assumption, marked or not."""

    def render(self, change):
        model = json.loads((FIXTURE / "c4-model.json").read_text(encoding="utf-8"))
        change(model)
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        with contextlib.redirect_stdout(io.StringIO()):
            run_analyzer(FIXTURE, tmp)
            (Path(tmp) / "c4-model.json").write_text(json.dumps(model), encoding="utf-8")
            render_c4.render(tmp, svg=False)
        report = (Path(tmp) / "ArchitectureReport.md").read_text(encoding="utf-8")
        start = report.index("### Assumptions")
        return report[start:report.index("###", start + 3)]

    def test_misspelled_assumption_still_reaches_the_assumptions_list(self):
        def change(model):
            person = model["people"][0]
            person["assumptions"] = person.pop("assumption")
        section = self.render(change)
        self.assertIn("- **Reader** (unmarked, no evidence): Searches the catalogue and buys books", section)

    def test_an_element_with_neither_evidence_nor_marking_is_listed(self):
        section = self.render(lambda m: next(c for c in m["containers"]
                                             if c["id"] == "bookshop-api").pop("evidence"))
        self.assertIn("- **Bookshop API** (unmarked, no evidence):", section)

    def test_an_evidenced_element_is_not_listed(self):
        section = self.render(lambda m: None)
        self.assertNotIn("Bookshop API", section)
        self.assertIn("- **Reader**: Searches the catalogue and buys books", section)


if __name__ == "__main__":
    unittest.main()
