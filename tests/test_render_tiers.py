"""
SPEC-06: tiered semantic checks (`tests/test_render_tiers.py`).

`validate()` in `scripts/render_c4` is now responsible for tier routing:
  - coverage gaps (facts not in the model and not in `excluded`) -> drift
  - unknown relationship or flow ids, duplicate ids -> errors (invalid)
  - remaining checks stay warnings (evidence, etc.)

A ValidationResult wins the worse tier: invalid > drift > ok.
"""
import json
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


if __name__ == "__main__":
    unittest.main()