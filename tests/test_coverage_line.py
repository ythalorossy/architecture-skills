"""
The `Coverage:` line render_c4.py prints after `Diagrams:`.

`validate()` answers "is this model consistent?". A model can be `ok`,
drift-free and warning-free while carrying no person, no flows and not one
component description -- the failure mode SKILL.md's Common-mistakes table
spends most of its rows on. `Coverage:` is how the script says "is it
finished?", and SKILL.md's "When Step 3 is finished" reads the numbers off it.

The freight fixture is the case worth pinning: the recorded Opus baseline is a
complete model, and the same fixture rendered facts-only is the empty end.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "c4-diagrams"
ANALYZE = SKILL / "scripts" / "analyze_repository.py"
RENDER = SKILL / "scripts" / "render_c4.py"
FREIGHT = ROOT / "tests" / "fixtures" / "repos" / "freight"
OPUS_MODEL = ROOT / "evals" / "baselines" / "2026-10-12-freight-opus" / "c4-model.json"


def _run(script, *args):
    env = os.environ.copy()
    env["C4_SVG"] = "0"
    return subprocess.run([sys.executable, str(script), *map(str, args)],
                          capture_output=True, text=True, env=env)


class CoverageLineTest(unittest.TestCase):
    """One case per end of the scale: a finished model, and no model at all."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = self.tmp / "out"
        analyzed = _run(ANALYZE, FREIGHT, "--output", self.out)
        self.assertEqual(analyzed.returncode, 0, analyzed.stderr)

    def test_a_finished_model_reports_full_coverage(self):
        shutil.copy(OPUS_MODEL, self.out / "c4-model.json")
        rendered = _run(RENDER, self.out)
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertIn("Coverage: facts 5/5, containers described 4/4, "
                      "components described 5/5, people 1, flows 2, code 3",
                      rendered.stdout)

    def test_facts_only_reports_the_empty_end(self):
        rendered = _run(RENDER, self.out, "--facts-only")
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertIn(", people 0, flows 0, code 0", rendered.stdout)

    def test_a_model_that_validates_clean_can_still_be_empty(self):
        """The discrimination: `ok` and warning-free, yet nothing described.

        This is what the line exists to catch -- the careless answer passes
        every check `validate()` makes.
        """
        facts = json.loads((self.out / "c4-facts.json").read_text())
        ids = [f["id"] for kind in ("containers", "data_stores", "external_systems")
               for f in facts[kind]]
        (self.out / "c4-model.json").write_text(json.dumps({
            "system": {"name": "Freight", "description": "Shipment tracking."},
            "people": [],
            "containers": [{"id": i, "name": i} for i in ids],
            "external_systems": [],
            "relationships": [],
            "components": {},
            "flows": [],
            "code": [],
            "excluded": [],
        }))
        rendered = _run(RENDER, self.out)
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertNotIn("DRIFT:", rendered.stdout)
        self.assertIn("components described 0/", rendered.stdout)
        self.assertIn(", people 0, flows 0, code 0", rendered.stdout)


if __name__ == "__main__":
    unittest.main()
