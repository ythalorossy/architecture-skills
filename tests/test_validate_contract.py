"""
Validator contract cases (AC4 / PE-11 Tier 0).

Each shape asserts two things per AC4:
  1. render() returns a dict whose `errors` list is non-empty and contains the
     expected per-case substring (e.g. "containers" for the string-section
     shape).
  2. No "Traceback" appears in the captured output — REVIEW FOCUS 4.

Today seven of eight shapes raise `JSONDecodeError`, `AttributeError`, or
`KeyError` from inside `render_c4.render` (render_c4.py:110,115,119,137,145,
760,762 — see `.serena/SPEC-02-traceability.md` §4/A-6 for the per-shape
call site). They are marked `@unittest.expectedFailure` until SPEC-06 makes
them return clean error strings without raising. The eighth shape (unknown
`facts` id) already returns an error and is tested as a passing case — see
`test_unknown_facts_id_returns_error` below and the report-back in
`/home/ysaldanha/lab/architecture-skills/.serena/SPEC-02-traceability.md` §4
for the discrepancy with the directive that asked for all eight to be
`expectedFailure`.

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
    """Return the AC4 case table plus the unknown_facts_id passing case."""

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
            "json",  # any SPEC-06 message naming the JSON parser will contain 'json'
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
    """The eight AC4 shapes, plus the unknown_facts_id passing case."""

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

    @unittest.expectedFailure
    def test_malformed_model_reports_error_not_traceback(self):
        """The seven crashing shapes today; SPEC-06 makes them return errors."""
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

    def test_unknown_facts_id_returns_error(self):
        """The eighth AC4 shape — the only one that is already passing today.

        The directive in the team-lead's brief marked all eight as
        `@expectedFailure`. Empirically the unknown-facts-id case already
        reaches validate() and returns the proper error (render_c4.py:127-132);
        it is therefore NOT marked `@expectedFailure`. This test pins the
        current behaviour so SPEC-06 cannot silently regress it.
        """
        for label, substring, (result, exc, captured) in self._run_table():
            if label != "unknown_facts_id":
                continue
            with self.subTest(shape=label):
                self.assertIsNone(exc, f"{label}: must not raise, got {exc!r}")
                self.assertNotIn("Traceback", captured, captured)
                errors = (result or {}).get("errors", [])
                self.assertIsInstance(errors, list)
                self.assertTrue(errors, f"{label}: expected non-empty errors, got {errors!r}")
                joined = "\n".join(errors)
                self.assertIn(substring, joined, errors)

    def test_error_path_return_lacks_success_keys(self):
        """Per A-3: the error path returns ONLY {"errors", "warnings"}.
        Consumers that read result["diagrams"] on this path today KeyError.
        Pin the contract."""
        for label, _substring, (result, exc, _captured) in self._run_table():
            if label != "unknown_facts_id":
                continue
            with self.subTest(shape=label):
                self.assertIsNone(exc)
                self.assertIn("errors", result)
                self.assertIn("warnings", result)
                self.assertNotIn("diagrams", result)
                self.assertNotIn("svg_failed", result)
                self.assertNotIn("facts_only", result)


# ---------- SPEC-06: ValidationResult + safe loader (Task 1) ----------

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
            # malformed-JSON case. AC2 requires the message to name the line
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


if __name__ == "__main__":
    unittest.main()