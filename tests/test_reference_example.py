"""
The worked example in assets/c4-model-reference.md is the model of the
synthetic fixture in tests/fixtures/repos/bookshop. These tests keep the two
identical, and keep the example valid against facts freshly generated from the
fixture, so an example can only come from a committed fixture (SPEC-01).
"""
import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import SKILL
from scripts import analyze_repository, code_diagrams, render_c4

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "repos" / "bookshop"
MODEL_FILE = FIXTURE / "c4-model.json"
REFERENCE = SKILL / "assets" / "c4-model-reference.md"
JSON_BLOCK = re.compile(r"^```json\n(.*?)^```", re.MULTILINE | re.DOTALL)
EVIDENCE = re.compile(r"^(?P<path>[^:\s]+):(?P<line>[1-9]\d*)$")


def load_model():
    return json.loads(MODEL_FILE.read_text(encoding="utf-8"))


def evidence_entries(model):
    """(element id, evidence entry) for every evidence entry in the model."""
    return [
        (element["id"], entry)
        for section in ("people", "containers", "external_systems")
        for element in model.get(section) or []
        for entry in element.get("evidence") or []
    ]


class ReferenceExampleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._output = tempfile.TemporaryDirectory()
        cls.output = Path(cls._output.name)
        # The real analyzer, without the SVG step (it needs Node.js and the network).
        with mock.patch.object(analyze_repository, "render_svg", return_value=False), \
                mock.patch.object(render_c4, "render", return_value={"status": "ok", "errors": [], "drift": [], "warnings": []}), \
                contextlib.redirect_stdout(io.StringIO()):
            analyze_repository.RepositoryAnalyzer(str(FIXTURE), str(cls.output)).run()
        cls.facts = json.loads((cls.output / "c4-facts.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls._output.cleanup()

    def test_reference_block_matches_fixture_model(self):
        blocks = JSON_BLOCK.findall(REFERENCE.read_text(encoding="utf-8"))
        self.assertTrue(blocks, f"no ```json block in {REFERENCE.name}")
        message = f"the example in {REFERENCE.name} must be a copy of {MODEL_FILE.relative_to(FIXTURE.parent)}"
        self.assertEqual(json.loads(blocks[0]), load_model(), message)
        no_space = lambda text: re.sub(r"\s+", "", text)
        self.assertEqual(no_space(blocks[0]), no_space(MODEL_FILE.read_text(encoding="utf-8")), message)

    def test_fixture_model_validates_against_fresh_facts(self):
        model = load_model()
        result = render_c4.validate(model, self.facts)
        self.assertEqual(result.status, "ok", f"the fixture model no longer matches the facts: {result.errors + result.drift + result.warnings}")
        self.assertEqual(result.errors, [], "the fixture model no longer matches the facts; update c4-model.json")
        self.assertEqual(result.warnings, [], "the example should render without warnings")
        errors, warnings, entries = code_diagrams.prepare(model, self.facts, self.output)
        self.assertEqual(errors, [], "the `code` entries no longer match the fixture code")
        self.assertEqual(warnings, [])
        self.assertTrue(entries)

    def test_example_evidence_resolves_in_fixture(self):
        entries = evidence_entries(load_model())
        self.assertTrue(entries)
        for element, entry in entries:
            with self.subTest(element=element, evidence=entry):
                match = EVIDENCE.match(entry)
                self.assertIsNotNone(match, f"{element}: evidence must be a full repo-relative path:line, got {entry!r}")
                path = (FIXTURE / match["path"]).resolve()
                self.assertTrue(path.is_relative_to(FIXTURE), f"{element}: {match['path']} is outside the fixture")
                self.assertTrue(path.is_file(), f"{element}: {match['path']} is not a file in the fixture")
                lines = len(path.read_text(encoding="utf-8").splitlines())
                self.assertLessEqual(int(match["line"]), lines, f"{element}: {entry} is past the end of the file ({lines} lines)")

    def test_example_has_no_elided_paths(self):
        for element, entry in evidence_entries(load_model()):
            with self.subTest(element=element, evidence=entry):
                self.assertNotIn("...", entry)
                self.assertNotIn("…", entry)

    def test_example_exercises_every_contract_feature(self):
        model = load_model()
        containers = model["containers"]
        flows = model["flows"]
        features = {
            "a person marked as an assumption": any(p.get("assumption") is True for p in model["people"]),
            "a container": any(c.get("type", "container") == "container" for c in containers),
            "an owned database": any(c.get("type") == "database" and not c.get("external") for c in containers),
            "a store with external: true": any(c.get("type") == "database" and c.get("external") is True for c in containers),
            "an external system": bool(model["external_systems"]),
            "a relationship": bool(model["relationships"]),
            "a components description": any(model["components"].values()),
            "a flow with a reply step": any(s.get("reply") is True for f in flows for s in f["steps"]),
            "a code entry": bool(model.get("code")),
            "an excluded fact with a reason": any(e.get("reason") for e in model.get("excluded") or []),
        }
        missing = [name for name, present in features.items() if not present]
        self.assertEqual(missing, [], "the example must show every contract feature")


if __name__ == "__main__":
    unittest.main()
