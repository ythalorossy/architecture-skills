"""
Validator contract cases.

Each shape asserts two things:
  1. render() returns a dict whose `errors` list is non-empty and contains the
     expected per-case substring (e.g. "containers" for the string-section
     shape).
  2. No "Traceback" appears in the captured output.

The seven shapes that used to crash return tiered `invalid` errors and
the eighth (unknown facts id) returns `drift`. All eight are plain passing
tests (the former `@unittest.expectedFailure` markers are removed).

The `c4-model.json` string is a CLI-layer wrapper (`render_c4.py:886`) and
must NOT be asserted on at the render() level — see A-7. The CLI-layer
wrapper is owned by `tests/test_cli.py`.
"""
import contextlib
import io
import json
import tempfile
import traceback
import unittest
from pathlib import Path

from helpers import write


# ---------- shared fixture data ----------

_WORKFLOW_CS = (
    "namespace Api.Workflow;\n"
    "public interface IWorkflowConductor { bool Change(long id); }\n"
    "public class WorkflowConductor : IWorkflowConductor\n"
    "{\n"
    "    public bool Change(long id) => true;\n"
    "}\n"
)


def _build_real_facts(tmp):
    """Build a real c4-facts.json by running the analyzer on a tiny C# repo.

    Returns (facts_dict, container_id, container_name). The facts dict has
    exactly one container ('api') so the unknown_facts_id case can attach
    an orphan data_store without colliding with anything else.
    """
    repo = Path(tmp) / "demo"
    write(repo, {
        "Api/Api.csproj": (
            '<Project Sdk="Microsoft.NET.Sdk.Web">'
            "<PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup>"
            "</Project>"
        ),
        "Api/Program.cs": "namespace Api;\npublic static class Program { public static void Main() { } }\n",
        "Api/Workflow/Workflow.cs": _WORKFLOW_CS,
    })
    from scripts.build_graph import build_dependency_graph
    from scripts.c4_facts import collect_facts
    facts = collect_facts(repo, build_dependency_graph(repo))
    container = facts["containers"][0]
    return facts, container["id"], container["name"]


# ---------- driver ----------

def _call_render(output):
    """Call render() and capture stdout, stderr, return value, and any exception.

    If render() raises, the traceback is rendered into `captured` via
    `traceback.format_exception` so the "no Traceback in output" assertion is
    meaningful today (render() does not print on its own; the traceback only
    appears in `captured` because we put it there, exactly the way an
    unhandled top-level exception would land on stderr).
    """
    from scripts.render_c4 import render
    stdout, stderr = io.StringIO(), io.StringIO()
    result, exc, tb_text = None, None, ""
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            result = render(output, svg=False)
        except Exception as ex:
            exc = ex
            tb_text = "".join(traceback.format_exception(type(ex), ex, ex.__traceback__))
    return result, exc, stdout.getvalue() + stderr.getvalue() + tb_text


# ---------- per-case models ----------

def _cases(facts, container_id, container_name):
    """The malformed-model case table plus the unknown_facts_id passing case."""

    base_model = {
        "system": {"name": "Demo", "description": ""},
        "people": [],
        "containers": [{"id": container_id, "name": container_name}],
        "external_systems": [],
        "relationships": [],
        "components": {},
        "flows": [],
        "excluded": [],
    }

    # Each tuple is (label, model_factory, expected_substring, writes_raw_model).
    # `model_factory(facts, container_id, container_name)` returns the model
    # dict (or `None` if `writes_raw_model` is True).
    return [
        (
            "malformed_json",
            lambda f, c, n: None,  # signals raw-bytes write below
            "json",  # a message naming the JSON parser contains 'json'
            True,    # write c4-model.json as raw bytes, not json.dumps
        ),
        (
            "top_level_list",
            lambda f, c, n: ["this", "is", "a", "list"],
            "list",  # crash today at "AttributeError: 'list' object has no attribute 'setdefault'"
            False,
        ),
        (
            "string_section",
            lambda f, c, n: {**base_model, "containers": "oops"},
            "containers",  # crash today at line 115: 'str' object has no attribute 'get'
            False,
        ),
        (
            "string_element",
            lambda f, c, n: {**base_model, "containers": ["oops"]},
            "containers",  # crash today at line 110: 'str' object has no attribute 'get'
            False,
        ),
        (
            "excluded_without_id",
            lambda f, c, n: {**base_model, "excluded": [{"reason": "no id"}]},
            "excluded",  # crash today at line 119: KeyError: 'id'
            False,
        ),
        (
            "flow_steps_str",
            lambda f, c, n: {
                **base_model,
                "flows": [{"id": "f1", "name": "Demo flow", "steps": "should be a list"}],
            },
            "steps",  # crash today at line 145: 'str' object has no attribute 'get'
            False,
        ),
        (
            "components_list",
            lambda f, c, n: {**base_model, "components": ["not", "a", "dict"]},
            "components",  # crash today at line 137: 'list' object has no attribute 'items'
            False,
        ),
        (
            "unknown_facts_id",
            lambda f, c, n: base_model,  # orphan data_store is added to facts, not the model
            "was found in the code but is not in the model",
            False,
        ),
    ]


# ---------- tests ----------

class ValidateContractTest(unittest.TestCase):
    """The eight malformed-model shapes, plus the unknown_facts_id passing case."""

    def _setup_case(self, case, facts, container_id, container_name):
        """Lay out facts+c4-model.json for one case in a fresh tmpdir."""
        label, factory, _substring, writes_raw = case
        out = Path(tempfile.mkdtemp()) / "out"
        out.mkdir(parents=True)
        (out / "c4-facts.json").write_text(json.dumps(facts), encoding="utf-8")
        if writes_raw:
            # malformed JSON: raw bytes, not json.dumps
            (out / "c4-model.json").write_text("{not valid json", encoding="utf-8")
        else:
            model = factory(facts, container_id, container_name)
            (out / "c4-model.json").write_text(json.dumps(model), encoding="utf-8")
        return out

    def _run_table(self):
        """Yield (label, expected_substring, result, exc, captured) for each case."""
        with tempfile.TemporaryDirectory() as tmp:
            facts, container_id, container_name = _build_real_facts(tmp)
            # For unknown_facts_id, attach an orphan data_store the model does not cover.
            facts_for_case = json.loads(json.dumps(facts))
            facts_for_case["data_stores"].append({
                "id": "deleted-store",
                "name": "Old store",
                "kind": "database",
                "technology": "Test",
                "evidence": ["old.csproj"],
                "path": "Old",
                "used_by": [],
                "compose_services": None,
            })

            for case in _cases(facts_for_case, container_id, container_name):
                label, _factory, substring, _raw = case
                out = self._setup_case(case, facts_for_case, container_id, container_name)
                yield label, substring, _call_render(out)

    def test_malformed_model_reports_error_not_traceback(self):
        """The seven shapes that used to crash now return errors."""
        for label, substring, (result, exc, captured) in self._run_table():
            if label == "unknown_facts_id":
                # This case is tested separately as a passing case below; skip here
                # so its current pass doesn't mask the seven failing ones.
                continue
            with self.subTest(shape=label):
                self.assertIsNone(
                    exc,
                    f"{label}: render() must not raise, got "
                    f"{type(exc).__name__ if exc else None}: {exc!r}",
                )
                self.assertNotIn(
                    "Traceback",
                    captured,
                    f"{label}: render() must not print a traceback; "
                    f"captured output: {captured!r}",
                )
                errors = (result or {}).get("errors", [])
                self.assertIsInstance(errors, list, f"{label}: errors must be a list")
                self.assertTrue(
                    errors,
                    f"{label}: expected non-empty errors list, got {errors!r}",
                )
                joined = "\n".join(errors)
                self.assertIn(
                    substring,
                    joined,
                    f"{label}: expected substring {substring!r} in errors; "
                    f"got {errors!r}",
                )

    def test_unknown_facts_id_returns_drift(self):
        """The eighth shape — a facts id not covered by the model.

        This is drift (not invalid): the model is structurally
        well-typed, it just hasn't been updated since the code added a new
        data store. The drift list carries the diagnostic, render() still
        draws the model, and the Unreviewed facts section is appended.
        """
        for label, substring, (result, exc, captured) in self._run_table():
            if label != "unknown_facts_id":
                continue
            with self.subTest(shape=label):
                self.assertIsNone(exc, f"{label}: must not raise, got {exc!r}")
                self.assertNotIn("Traceback", captured, captured)
                self.assertEqual(
                    (result or {}).get("status"), "drift",
                    f"{label}: expected status 'drift', got {result!r}",
                )
                drift = (result or {}).get("drift", [])
                self.assertIsInstance(drift, list)
                self.assertTrue(drift, f"{label}: expected non-empty drift, got {drift!r}")
                joined = "\n".join(drift)
                self.assertIn(substring, joined, drift)

    def test_error_path_return_lacks_success_keys(self):
        """The error path returns the full tiered shape.
        Consumers that read result["diagrams"] must be safe even on invalid
        (render() still produces a facts-only model)."""
        for label, _substring, (result, exc, _captured) in self._run_table():
            if label == "malformed_json":
                # Malformed JSON is the cleanest invalid path: the model is
                # dropped and the facts-only model is drawn. Status must be
                # 'invalid' and the result must still carry 'diagrams' and
                # 'facts_only' so consumers can introspect.
                with self.subTest(shape=label):
                    self.assertIsNone(exc)
                    self.assertEqual(result["status"], "invalid")
                    self.assertIn("errors", result)
                    self.assertIn("warnings", result)
                    self.assertIn("diagrams", result)
                    self.assertIn("facts_only", result)
                    self.assertTrue(result["facts_only"])


# ---------- ValidationResult + safe loader (Task 1) ----------

class LoaderResultTest(unittest.TestCase):
    """Task 1: ValidationResult status derivation and safe loader errors.

    Each loader call returns a ValidationResult with status, errors, drift,
    warnings lists. Status is derived: errors -> invalid, else drift -> drift,
    else ok. Messages are prefixed `c4-model.json:` and JSON parse errors
    name the line and column of the failure.
    """

    def test_bad_json_reports_line_and_column(self):
        """Trailing comma on line 3 -> message names line 3 and a column."""
        from scripts.model_check import load_model

        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "c4-model.json"
            # A trailing comma after a closing bracket is the canonical
            # malformed-JSON case. The message must name the line
            # and column of the trailing comma (line 3 here), not the EOF
            # position the stdlib parser reports.
            model_path.write_text(
                '{\n  "system": {"name": "Demo"},\n  "containers": [],\n',
                encoding="utf-8",
            )
            result = load_model(model_path)

        self.assertEqual(result.status, "invalid")
        self.assertEqual(len(result.errors), 1)
        message = result.errors[0]
        self.assertTrue(
            message.startswith("c4-model.json: line 3"),
            f"expected 'c4-model.json: line 3 ...' prefix, got {message!r}",
        )
        self.assertIn("column", message)

    def test_top_level_list_is_invalid(self):
        """A list at the top level is invalid (it must be an object)."""
        from scripts.model_check import load_model

        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "c4-model.json"
            model_path.write_text("[1, 2, 3]", encoding="utf-8")
            result = load_model(model_path)

        self.assertEqual(result.status, "invalid")
        self.assertTrue(result.errors)

    def test_valid_object_returns_ok(self):
        """A well-formed object returns status ok with empty lists."""
        from scripts.model_check import load_model

        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "c4-model.json"
            model_path.write_text('{"system": {"name": "Demo"}}', encoding="utf-8")
            result = load_model(model_path)

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.errors, [])
        self.assertEqual(result.drift, [])
        self.assertEqual(result.warnings, [])


# ---------- Structural pre-check (Task 2) ----------

class StructuralShapesTest(unittest.TestCase):
    """Check_structure catches every malformed shape with a JSON path.

    Each shape must produce `status == "invalid"` and an error message that
    names the JSON path of the offending value (e.g. `containers[3]`,
    `excluded[0].id`, `flows[0].steps`).
    """

    def _run_one(self, model: dict):
        from scripts.model_check import check_structure

        return check_structure(model)

    def test_containers_str_reports_path(self):
        result = self._run_one({"system": {"name": "Demo"}, "containers": "oops"})
        self.assertEqual(result.status, "invalid")
        joined = "\n".join(result.errors)
        self.assertIn("containers", joined)

    def test_system_str_reports_path(self):
        result = self._run_one({"system": "not a dict"})
        self.assertEqual(result.status, "invalid")
        joined = "\n".join(result.errors)
        self.assertIn("system", joined)

    def test_element_str_reports_index(self):
        result = self._run_one({
            "system": {"name": "Demo"},
            "containers": [{"id": "a", "name": "A"}, "oops", {"id": "c", "name": "C"}],
        })
        self.assertEqual(result.status, "invalid")
        joined = "\n".join(result.errors)
        self.assertIn("containers[1]", joined)

    def test_excluded_no_id_reports_path(self):
        result = self._run_one({
            "system": {"name": "Demo"},
            "excluded": [{"reason": "missing id"}],
        })
        self.assertEqual(result.status, "invalid")
        joined = "\n".join(result.errors)
        self.assertIn("excluded[0]", joined)
        self.assertIn("id", joined)

    def test_flow_steps_str_reports_path(self):
        result = self._run_one({
            "system": {"name": "Demo"},
            "flows": [{"name": "Flow 1", "steps": "should be a list"}],
        })
        self.assertEqual(result.status, "invalid")
        joined = "\n".join(result.errors)
        self.assertIn("flows[0].steps", joined)

    def test_components_list_reports_path(self):
        result = self._run_one({
            "system": {"name": "Demo"},
            "components": ["not", "a", "dict"],
        })
        self.assertEqual(result.status, "invalid")
        joined = "\n".join(result.errors)
        self.assertIn("components", joined)

    def test_components_description_str_reports_path(self):
        result = self._run_one({
            "system": {"name": "Demo"},
            "components": {"c1": "should be a list"},
        })
        self.assertEqual(result.status, "invalid")
        joined = "\n".join(result.errors)
        self.assertIn("components", joined)
        self.assertIn("c1", joined)

    def test_relationship_not_object_reports_index(self):
        result = self._run_one({
            "system": {"name": "Demo"},
            "relationships": [{"from": "a", "to": "b"}, "oops"],
        })
        self.assertEqual(result.status, "invalid")
        joined = "\n".join(result.errors)
        self.assertIn("relationships[1]", joined)

    def test_missing_system_name_reports_path(self):
        result = self._run_one({"system": {}})
        self.assertEqual(result.status, "invalid")
        joined = "\n".join(result.errors)
        self.assertIn("system.name", joined)

    def test_well_typed_object_returns_ok(self):
        result = self._run_one({
            "system": {"name": "Demo"},
            "people": [],
            "containers": [{"id": "c1", "name": "C"}],
            "external_systems": [],
            "relationships": [{"from": "c1", "to": "c1", "description": ""}],
            "components": {"c1": {"c1.core": "Core logic"}},
            "flows": [],
            "excluded": [],
        })
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.errors, [])


if __name__ == "__main__":
    unittest.main()