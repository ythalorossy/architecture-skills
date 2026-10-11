"""
SPEC-06: tiered semantic checks (`tests/test_render_tiers.py`).

`validate()` in `scripts/render_c4` is now responsible for tier routing:
  - coverage gaps (facts not in the model and not in `excluded`) -> drift
  - unknown relationship or flow ids, duplicate ids -> errors (invalid)
  - remaining checks stay warnings (evidence, etc.)

A ValidationResult wins the worse tier: invalid > drift > ok.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "c4-diagrams"
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from scripts.render_c4 import validate  # noqa: E402


def _facts_with_two_containers():
    """Tiny c4-facts.json with two containers and no other sections."""
    return {
        "repository": "demo",
        "containers": [
            {"id": "a", "name": "A", "kind": "service", "technology": "Python",
             "evidence": [], "path": "a", "used_by": [], "components": {}, "code_components": {},
             "inventory": [], "compose_services": None, "relationships": []},
            {"id": "b", "name": "B", "kind": "service", "technology": "Python",
             "evidence": [], "path": "b", "used_by": [], "components": {}, "code_components": {},
             "inventory": [], "compose_services": None, "relationships": []},
        ],
        "data_stores": [],
        "external_systems": [],
        "relationships": [],
    }


def _valid_model_for(container_ids):
    return {
        "system": {"name": "Demo", "description": ""},
        "people": [],
        "containers": [{"id": cid, "name": cid.upper()} for cid in container_ids],
        "external_systems": [],
        "relationships": [],
        "components": {},
        "flows": [],
        "excluded": [],
    }


def _write_facts_and_model(out_dir: Path, facts: dict, model, *, with_report: bool = False) -> None:
    """Lay out facts + c4-model.json for a render() call.

    `with_report=True` writes a stub ArchitectureReport.md that has the
    [//]: # (c4:start) ... [//]: # (c4:end) markers; render() replaces the
    block inside them on a subsequent run.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "c4-facts.json").write_text(json.dumps(facts), encoding="utf-8")
    if model is not None:
        if isinstance(model, (dict, list)):
            (out_dir / "c4-model.json").write_text(json.dumps(model), encoding="utf-8")
        else:
            # Raw bytes (malformed JSON test cases).
            (out_dir / "c4-model.json").write_bytes(model)
    if with_report:
        (out_dir / "ArchitectureReport.md").write_text(
            "# Report\n\n[//]: # (c4:start)\n\n[//]: # (c4:end)\n",
            encoding="utf-8",
        )


# ---------- Task 4: render() per tier ----------

class RenderTierTest(unittest.TestCase):
    """Task 4: render() returns status, errors, drift, warnings, diagrams.

    On drift the model is rendered and an `Unreviewed facts` section is
    appended inside the C4 block. On invalid the model is dropped and the
    facts-only model is drawn; errors are preserved.
    """

    def test_drift_renders_with_model_and_lists_unreviewed(self):
        from scripts.render_c4 import render

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            facts = _facts_with_two_containers()
            model = _valid_model_for(["a"])  # `b` is unreviewed
            _write_facts_and_model(out, facts, model, with_report=True)

            result = render(out, svg=False)

            self.assertEqual(result["status"], "drift")
            self.assertIn("c4-context", result["diagrams"])
            report = (out / "ArchitectureReport.md").read_text(encoding="utf-8")
            self.assertIn("### Unreviewed facts", report)
            self.assertIn("b", report)

    def test_unreviewed_facts_name_their_kind(self):
        from scripts.render_c4 import _unreviewed_facts_section

        facts = {
            "containers": [{"id": "api", "name": "API"}],
            "data_stores": [{"id": "db-postgresql", "name": "PostgreSQL"}],
            "external_systems": [{"id": "ext-stripe", "name": "Stripe"}],
        }
        drift = ["api is new", "db-postgresql is new", "ext-stripe is new"]
        table = "\n".join(_unreviewed_facts_section(facts, drift))
        self.assertIn("| `api` | API | container |", table)
        self.assertIn("| `db-postgresql` | PostgreSQL | data store |", table)
        self.assertIn("| `ext-stripe` | Stripe | external system |", table)

    def test_invalid_falls_back_to_facts_only(self):
        from scripts.render_c4 import render

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            facts = _facts_with_two_containers()
            model = _valid_model_for(["a", "b"])
            model["relationships"] = [{"from": "a", "to": "ghost"}]
            _write_facts_and_model(out, facts, model)

            result = render(out, svg=False)

            self.assertEqual(result["status"], "invalid")
            self.assertTrue(result["facts_only"])
            self.assertTrue(result["errors"])

    def test_malformed_json_falls_back_to_facts_only(self):
        from scripts.render_c4 import render

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            facts = _facts_with_two_containers()
            _write_facts_and_model(out, facts, b"{not valid json")

            result = render(out, svg=False)

            self.assertEqual(result["status"], "invalid")
            self.assertTrue(result["facts_only"])
            self.assertTrue(result["errors"])
            joined = "\n".join(result["errors"])
            self.assertIn("c4-model.json:", joined)

    def test_ok_renders_with_model(self):
        from scripts.render_c4 import render

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            facts = _facts_with_two_containers()
            model = _valid_model_for(["a", "b"])
            _write_facts_and_model(out, facts, model)

            result = render(out, svg=False)

            self.assertEqual(result["status"], "ok")
            self.assertIn("c4-context", result["diagrams"])


class TieredValidationTest(unittest.TestCase):
    """Task 3: validate() returns a ValidationResult with status, errors,
    drift and warnings."""

    def test_uncovered_fact_is_drift(self):
        """A valid model that misses one fact -> status drift, fact in drift."""
        facts = _facts_with_two_containers()
        # Model only covers `a`; `b` is uncovered.
        model = _valid_model_for(["a"])

        result = validate(model, facts)

        self.assertEqual(result.status, "drift")
        self.assertEqual(result.errors, [])
        joined = "\n".join(result.drift)
        self.assertIn("b", joined)

    def test_unknown_relationship_id_is_invalid(self):
        facts = _facts_with_two_containers()
        model = _valid_model_for(["a", "b"])
        model["relationships"] = [{"from": "a", "to": "ghost"}]

        result = validate(model, facts)

        self.assertEqual(result.status, "invalid")
        self.assertTrue(result.errors)

    def test_duplicate_id_is_invalid(self):
        facts = _facts_with_two_containers()
        model = _valid_model_for(["a", "b"])
        model["people"] = [{"id": "a", "name": "Alice"}]  # duplicate with container

        result = validate(model, facts)

        self.assertEqual(result.status, "invalid")
        self.assertTrue(any("duplicate" in e.lower() or "a" in e for e in result.errors))

    def test_invalid_beats_drift(self):
        """When both an invalid and a drift item exist, status is invalid."""
        facts = _facts_with_two_containers()
        model = _valid_model_for(["a"])  # b is drift
        model["relationships"] = [{"from": "a", "to": "ghost"}]  # invalid

        result = validate(model, facts)

        self.assertEqual(result.status, "invalid")
        self.assertTrue(result.errors)
        self.assertTrue(result.drift)

    def test_well_typed_valid_model_is_ok(self):
        facts = _facts_with_two_containers()
        model = _valid_model_for(["a", "b"])

        result = validate(model, facts)

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.errors, [])
        self.assertEqual(result.drift, [])


# ---------- Task 5: CLI exit codes ----------

RENDER_CLI = SKILL / "scripts" / "render_c4.py"
BOOKSHOP = ROOT / "tests" / "fixtures" / "repos" / "bookshop"


def _analyzed_bookshop(tmp: Path) -> Path:
    """Run the real analyzer on the bookshop fixture; return the output folder.

    The fixture model is copied in afterwards so each test controls c4-model.json.
    """
    from helpers import run_analyzer

    out = tmp / "out"
    run_analyzer(BOOKSHOP, out, no_svg=True)
    shutil.copy(BOOKSHOP / "c4-model.json", out / "c4-model.json")
    return out


def _fixture_model() -> dict:
    return json.loads((BOOKSHOP / "c4-model.json").read_text(encoding="utf-8"))


def _run_cli(out: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RENDER_CLI), str(out), "--no-svg", *extra],
        capture_output=True, text=True, timeout=120,
    )


class CliExitCodeTest(unittest.TestCase):
    """Task 5: ok and drift exit 0, invalid exits 1, drift with --strict exits 2.

    A drift run prints a `DRIFT:` line on stdout so the agent sees it without
    reading the report.
    """

    def test_cli_exit_codes_ok_drift_invalid_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = _analyzed_bookshop(Path(tmp))

            ok = _run_cli(out)
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertNotIn("DRIFT:", ok.stdout)

            drifted = _fixture_model()
            drifted["containers"] = [c for c in drifted["containers"] if c["id"] != "db-elasticsearch"]
            drifted["relationships"] = [
                r for r in drifted["relationships"]
                if "db-elasticsearch" not in (r["from"], r["to"])
            ]
            (out / "c4-model.json").write_text(json.dumps(drifted), encoding="utf-8")
            drift = _run_cli(out)
            self.assertEqual(drift.returncode, 0, drift.stderr)
            self.assertIn("DRIFT:", drift.stdout)
            self.assertIn("db-elasticsearch", drift.stdout)

            strict = _run_cli(out, "--strict")
            self.assertEqual(strict.returncode, 2, strict.stderr)

            broken = _fixture_model()
            broken["relationships"].append({"from": "bookshop-api", "to": "ghost", "description": "x"})
            (out / "c4-model.json").write_text(json.dumps(broken), encoding="utf-8")
            invalid = _run_cli(out)
            self.assertEqual(invalid.returncode, 1, invalid.stderr)


class ErrorPrefixTest(unittest.TestCase):
    """AC1/AC6: every invalid-tier message starts `c4-model.json:` and names a JSON path."""

    def test_every_invalid_shape_message_is_prefixed(self):
        from scripts.render_c4 import render

        facts = _facts_with_two_containers()
        base = _valid_model_for(["a", "b"])
        shapes = {
            "system-str": {**base, "system": "not a dict"},
            "element-str": {**base, "containers": ["oops"]},
            "excluded-noid": {**base, "excluded": [{"reason": "no id"}]},
            "flow-steps-str": {**base, "flows": [{"id": "f", "name": "F", "steps": "x"}]},
            "unknown-relationship": {**base, "relationships": [{"from": "a", "to": "ghost"}]},
            "duplicate-id": {**base, "people": [{"id": "a", "name": "Alice"}]},
        }
        for label, model in shapes.items():
            with self.subTest(shape=label), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "out"
                _write_facts_and_model(out, facts, model)
                result = render(out, svg=False)
                self.assertEqual(result["status"], "invalid")
                self.assertTrue(result["errors"])
                for message in result["errors"]:
                    self.assertTrue(message.startswith("c4-model.json:"), message)


if __name__ == "__main__":
    unittest.main()