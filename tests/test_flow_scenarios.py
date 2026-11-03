"""Flow scenarios (optional `scenarios` on a flow): structure checks."""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401  (puts the c4 scripts on sys.path)
from helpers import run_analyzer
from scripts import model_check, render_c4

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


class ScenarioValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            cls.facts, _ = run_analyzer(FIXTURE, tmp)
        cls.reference = json.loads((FIXTURE / "c4-model.json").read_text(encoding="utf-8"))

    def model(self):
        model = copy.deepcopy(self.reference)
        flow = model["flows"][0]
        flow.pop("scenarios", None)
        steps = [copy.deepcopy(s) for s in flow["steps"][:3]]
        steps[0]["payload"] = {"type": "dict", "fields": ["book_id"]}
        flow["scenarios"] = [{"id": "happy", "name": "Happy path", "given": "a stocked book",
                              "steps": steps, "evidence": ["web/src/main.tsx:15"]}]
        return model

    def validate(self, model):
        return render_c4.validate(model, self.facts, repo=FIXTURE)

    def scenario(self, model):
        return model["flows"][0]["scenarios"][0]

    def test_valid_scenario_validates_ok(self):
        result = self.validate(self.model())
        self.assertEqual(result.errors, [])
        self.assertFalse([w for w in result.warnings if "scenario" in w], result.warnings)

    def test_unknown_scenario_step_end_is_an_error(self):
        model = self.model()
        self.scenario(model)["steps"][0]["to"] = "nowhere"
        errors = self.validate(model).errors
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("scenarios[0].steps[0]", errors[0])
        self.assertIn("unknown to 'nowhere'", errors[0])

    def test_unknown_keys_warn_with_did_you_mean(self):
        model = self.model()
        scenario = self.scenario(model)
        scenario["givne"] = "x"
        scenario["steps"][0]["payload"]["feilds"] = ["a"]
        scenario["steps"][2]["store"] = {"targt": "orders", "target": "orders"}
        warnings = [w for w in self.validate(model).warnings if "unknown key" in w]
        self.assertEqual(len(warnings), 3, warnings)
        for warning in warnings:
            self.assertIn("did you mean", warning)

    def test_store_kind_and_operation_outside_vocabulary_warn(self):
        model = self.model()
        steps = self.scenario(model)["steps"]
        steps.append({"from": "bookshop.orders", "to": "db-postgresql", "description": "save",
                      "store": {"target": "orders", "kind": "tabel", "operation": "write"}})
        warnings = self.validate(model).warnings
        kind = [w for w in warnings if "kind" in w and "'tabel'" in w]
        operation = [w for w in warnings if "operation" in w and "'write'" in w]
        self.assertEqual(len(kind), 1, warnings)
        self.assertEqual(len(operation), 1, warnings)
        self.assertIn("table", kind[0])
        self.assertIn("upsert", operation[0])

    def test_store_on_step_without_data_store_end_warns(self):
        model = self.model()
        self.scenario(model)["steps"][2]["store"] = {"target": "orders", "kind": "table", "operation": "insert"}
        warnings = [w for w in self.validate(model).warnings if "store" in w and "data store" in w]
        self.assertEqual(len(warnings), 1, warnings)

    def test_store_on_read_reply_from_store_is_accepted(self):
        model = self.model()
        self.scenario(model)["steps"].append({
            "from": "db-postgresql", "to": "bookshop.orders", "reply": True, "description": "rows",
            "store": {"target": "orders", "kind": "table", "operation": "read"}})
        warnings = [w for w in self.validate(model).warnings if "store" in w]
        self.assertEqual(warnings, [])

    def test_scenario_without_evidence_or_assumption_warns(self):
        model = self.model()
        scenario = self.scenario(model)
        scenario.pop("evidence")
        for step in scenario["steps"]:
            step.pop("evidence", None)
        warnings = [w for w in self.validate(model).warnings
                    if "scenario" in w and "no evidence and not marked as an assumption" in w]
        self.assertEqual(len(warnings), 1, warnings)

    def test_duplicate_scenario_ids_warn(self):
        model = self.model()
        flow = model["flows"][0]
        flow["scenarios"].append(copy.deepcopy(flow["scenarios"][0]))
        warnings = [w for w in self.validate(model).warnings if "duplicate scenario id" in w]
        self.assertEqual(len(warnings), 1, warnings)

    def test_scenarios_without_ids_are_not_duplicates(self):
        model = self.model()
        flow = model["flows"][0]
        flow["scenarios"][0].pop("id")
        second = copy.deepcopy(flow["scenarios"][0])
        second["name"] = "Another path"
        flow["scenarios"].append(second)
        warnings = [w for w in self.validate(model).warnings if "duplicate scenario id" in w]
        self.assertEqual(warnings, [])

    def test_payload_on_flow_step_warns_and_is_ignored(self):
        base = copy.deepcopy(self.reference)
        base["flows"][0].pop("scenarios", None)
        model = copy.deepcopy(base)
        model["flows"][0]["steps"][0]["payload"] = {"type": "dict", "fields": ["a"]}
        warnings = [w for w in self.validate(model).warnings if "unknown key" in w]
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("flows[0].steps[0]", warnings[0])
        self.assertIn("'payload'", warnings[0])
        drawn = lambda m: [d[:3] for d in render_c4.flow_diagrams(m, self.facts)]
        self.assertEqual(drawn(model), drawn(base))

    def test_unproven_scenario_steps_are_listed_as_assumptions(self):
        model = self.model()
        scenario = self.scenario(model)
        scenario["steps"][1].pop("evidence", None)
        scenario["steps"][1]["assumption"] = True
        items = render_c4._assumptions(model)
        line = (f"- **{model['flows'][0]['name']} · Happy path**, step 2 "
                f"({scenario['steps'][1]['from']} → {scenario['steps'][1]['to']}): "
                f"{scenario['steps'][1]['description']}")
        self.assertIn(line, items)

    def test_assumption_scenario_is_listed_with_its_given(self):
        model = self.model()
        scenario = self.scenario(model)
        scenario["assumption"] = True
        items = render_c4._assumptions(model)
        self.assertIn(f"- **{model['flows'][0]['name']} · Happy path** (scenario): a stocked book", items)
        scenario.pop("given")
        self.assertIn(f"- **{model['flows'][0]['name']} · Happy path** (scenario): no starting conditions",
                      render_c4._assumptions(model))


class ScenarioDiagramTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            cls.facts, _ = run_analyzer(FIXTURE, tmp)
        cls.reference = json.loads((FIXTURE / "c4-model.json").read_text(encoding="utf-8"))

    # flow_diagrams output of the bookshop reference model, captured before
    # _step_line was factored out of it.
    BASELINE_FLOW_MERMAID = '---\ntitle: "Reader buys a book"\n---\nsequenceDiagram\n    actor reader as Reader\n    participant bookshop_web as Web app\n    participant web_src_api as web/src/api\n    participant bookshop_main as bookshop.main\n    participant bookshop_orders as bookshop.orders\n    participant ext_payments_example as Payment provider\n    participant db_postgresql as Orders database\n    reader->>bookshop_web: Clicks Buy on a book\n    web_src_api->>bookshop_main: POST /api/orders [JSON/HTTPS]\n    bookshop_main->>bookshop_orders: Places the order\n    bookshop_orders->>ext_payments_example: POST /v1/charges [HTTPS]\n    bookshop_orders->>db_postgresql: Inserts the order with its charge id [psycopg]\n    bookshop_main-->>web_src_api: Order id and charge id\n'

    def model(self, scenarios=None):
        model = copy.deepcopy(self.reference)
        flow = model["flows"][0]
        flow.pop("scenarios", None)
        steps = [copy.deepcopy(s) for s in flow["steps"][:3]]
        if scenarios is None:
            scenarios = [{"id": "payment-declined", "name": "Payment declined", "steps": steps}]
        flow["scenarios"] = scenarios
        return model

    def steps(self):
        return [copy.deepcopy(s) for s in self.reference["flows"][0]["steps"][:3]]

    def diagrams(self, model):
        return render_c4.scenario_diagrams(model, self.facts)

    def messages(self, mermaid):
        return [l for l in mermaid.splitlines() if "->>" in l or "-)" in l or "-->>" in l]

    def test_flow_diagrams_are_unchanged_by_refactor(self):
        model = copy.deepcopy(self.reference)
        model["flows"][0].pop("scenarios", None)
        result = render_c4.flow_diagrams(model, self.facts)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][2], self.BASELINE_FLOW_MERMAID)

    def test_scenario_diagram_stem_and_title(self):
        stem, flow_stem, title, mermaid, given = self.diagrams(self.model())[0]
        self.assertEqual(stem, "c4-flow-place-order--payment-declined")
        self.assertEqual(flow_stem, "c4-flow-place-order")
        self.assertEqual(title, "Reader buys a book \u00b7 Payment declined")
        self.assertEqual(given, "")
        self.assertTrue(mermaid.startswith("---\ntitle:"))
        self.assertIn("sequenceDiagram", mermaid)

    def test_given_is_returned(self):
        steps = self.steps()
        model = self.model([{"id": "x", "name": "X", "given": "a stocked book", "steps": steps}])
        self.assertEqual(self.diagrams(model)[0][4], "a stocked book")

    def with_data(self, **data):
        steps = self.steps()
        steps[0].update(data)
        return self.diagrams(self.model([{"id": "x", "name": "X", "steps": steps}]))[0][3]

    def test_payload_line(self):
        mermaid = self.with_data(payload={"type": "dict", "fields": ["book_id", "quantity", "card_token"]})
        self.assertIn("<br/>dict {book_id, quantity, card_token}", self.messages(mermaid)[0])

    def test_payload_type_alone_without_fields(self):
        mermaid = self.with_data(payload={"type": "tuple"})
        line = self.messages(mermaid)[0]
        self.assertIn("<br/>tuple", line)
        self.assertNotIn("{", line)

    def test_fields_beyond_four_collapse(self):
        mermaid = self.with_data(payload={"type": "T", "fields": list("abcdef")})
        self.assertIn("{a, b, c, d, \u2026}", self.messages(mermaid)[0])

    def test_store_text(self):
        store = {"operation": "insert", "target": "orders", "kind": "table"}
        mermaid = self.with_data(store=store)
        self.assertIn("<br/>INSERT orders (table)", self.messages(mermaid)[0])
        mermaid = self.with_data(store=store, payload={"type": "dict", "fields": ["a"]})
        self.assertIn("<br/>dict {a} \u00b7 INSERT orders (table)", self.messages(mermaid)[0])

    def test_store_without_operation_or_kind(self):
        self.assertEqual(render_c4._data_text({"store": {"target": "orders"}}), "orders")
        self.assertEqual(render_c4._data_text({}), "")

    def test_payload_text_is_escaped(self):
        mermaid = self.with_data(payload={"type": "Map<String; #Order>", "fields": ["a;b"]})
        line = self.messages(mermaid)[0]
        data = line.split("<br/>", 1)[1]
        self.assertNotIn(";", data.replace("#59;", "").replace("#35;", "").replace("#lt;", "").replace("#gt;", ""))
        self.assertNotIn("#Order", data)
        self.assertEqual(line.count("<br/>"), 1)

    def test_stem_uses_flow_name_when_id_missing(self):
        model = self.model()
        model["flows"][0].pop("id")
        stem, flow_stem, *_ = self.diagrams(model)[0]
        flow_stem_now = render_c4.flow_diagrams(model, self.facts)[0][0]
        self.assertEqual(flow_stem, flow_stem_now)
        self.assertTrue(stem.startswith("c4-flow-reader-buys-a-book--"), stem)

    def test_colliding_scenario_slugs_get_distinct_stems(self):
        steps = self.steps()
        model = self.model([{"id": "card-declined", "name": "A", "steps": steps},
                            {"name": "Card declined", "steps": copy.deepcopy(steps)}])
        stems = [d[0] for d in self.diagrams(model)]
        self.assertEqual(len(set(stems)), 2)
        self.assertTrue(stems[0].endswith("--card-declined"), stems)
        self.assertTrue(stems[1].endswith("--card-declined-2"), stems)

    def test_unproven_scenario_step_gets_question_mark(self):
        steps = self.steps()
        for step in steps:
            step.pop("assumption", None)
            step["evidence"] = ["a.py:1"]
        steps[1].pop("evidence")
        steps[1]["assumption"] = True
        model = self.model([{"id": "x", "name": "X", "steps": steps}])
        lines = self.messages(self.diagrams(model)[0][3])
        self.assertEqual([("(?)" in l) for l in lines], [False, True, False])

    def test_assumption_flow_marks_scenario_steps(self):
        steps = self.steps()
        for step in steps:
            step.pop("assumption", None)
            step.pop("evidence", None)
        model = self.model([{"id": "x", "name": "X", "steps": steps}])
        model["flows"][0]["assumption"] = True
        lines = self.messages(self.diagrams(model)[0][3])
        self.assertTrue(all("(?)" in l for l in lines), lines)

    def test_flows_without_scenarios_give_no_scenario_diagrams(self):
        self.assertEqual(self.diagrams(self.model([])), [])


if __name__ == "__main__":
    unittest.main()
