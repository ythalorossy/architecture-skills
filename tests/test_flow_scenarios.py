"""Flow scenarios (optional `scenarios` on a flow): structure checks."""
import copy
import json
import unittest
from pathlib import Path

import helpers  # noqa: F401  (puts the c4 scripts on sys.path)
from scripts import model_check

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "repos" / "bookshop"


class ScenarioStructureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = json.loads((FIXTURE / "c4-model.json").read_text(encoding="utf-8"))

    def model(self):
        model = copy.deepcopy(self.reference)
        flow = model["flows"][0]
        steps = [copy.deepcopy(s) for s in flow["steps"][:2]]
        steps[0]["payload"] = {"type": "dict", "fields": ["book_id"]}
        flow["scenarios"] = [{"id": "happy", "name": "Happy path", "steps": steps}]
        return model

    def errors(self, model):
        return model_check.check_structure(model).errors

    def test_valid_scenario_has_no_structure_errors(self):
        self.assertEqual(self.errors(self.model()), [])

    def test_scenarios_must_be_a_list(self):
        model = self.model()
        model["flows"][0]["scenarios"] = {}
        errors = self.errors(model)
        self.assertEqual(len(errors), 1)
        self.assertIn("flows[0].scenarios", errors[0])
        self.assertIn("expected a list", errors[0])

    def test_scenario_needs_name_and_steps(self):
        model = self.model()
        model["flows"][0]["scenarios"] = [{"id": "x"}]
        errors = self.errors(model)
        self.assertTrue(any("scenarios[0]" in e and "name" in e for e in errors), errors)
        self.assertTrue(any("scenarios[0]" in e and "steps" in e for e in errors), errors)

    def test_payload_must_be_object_with_string_type(self):
        model = self.model()
        step = model["flows"][0]["scenarios"][0]["steps"][0]
        step["payload"] = "dict"
        self.assertTrue(any(".payload" in e for e in self.errors(model)))
        step["payload"] = {"fields": []}
        self.assertTrue(any(".payload" in e and "'type'" in e for e in self.errors(model)))

    def test_payload_fields_must_be_strings(self):
        model = self.model()
        model["flows"][0]["scenarios"][0]["steps"][0]["payload"]["fields"] = ["a", 3]
        self.assertTrue(any("fields" in e for e in self.errors(model)))

    def test_store_needs_target(self):
        model = self.model()
        model["flows"][0]["scenarios"][0]["steps"][0]["store"] = {"kind": "table"}
        self.assertTrue(any(".store" in e and "'target'" in e for e in self.errors(model)))


if __name__ == "__main__":
    unittest.main()
