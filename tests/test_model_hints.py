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
        self.assertTrue(any("unknown to id 'bookshop-wb' (did you mean 'bookshop-web'?)" in e
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

    def test_excluded_needs_a_reason(self):
        result = self.check(lambda m: m["excluded"][0].pop("reason"))
        self.assertIn("excluded ext-covers-example: give a reason, so readers know why it is left out", result.warnings)

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

if __name__ == "__main__":
    unittest.main()
