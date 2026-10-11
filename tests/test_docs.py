"""
The user docs stay true to the code: every CLI option is documented in the
README, and the committed example output matches what the skill produces.
"""
import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT, run_analyzer

from scripts import render_c4

SCRIPTS = REPO_ROOT / "skills" / "c4-diagrams" / "scripts"
EXAMPLE = REPO_ROOT / "examples" / "bookshop"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "repos" / "bookshop"


def _options(script):
    """Long options a script's --help lists (hidden ones are not listed)."""
    help_text = subprocess.run([sys.executable, str(SCRIPTS / script), "--help"],
                               capture_output=True, text=True).stdout
    return sorted(set(re.findall(r"(--[a-z][a-z-]+)", help_text)) - {"--help"})


class ReadmeCommandReferenceTest(unittest.TestCase):
    def test_every_option_is_documented(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        reference = readme[readme.index("## Command reference"):readme.index("## Troubleshooting")]
        for script in ("analyze_repository.py", "render_c4.py"):
            section = reference[reference.index(f"### `{script}`"):]
            section = section[:section.find("\n### ", 1)] if "\n### " in section[1:] else section
            for option in _options(script):
                self.assertIn(f"`{option}", section, f"{script} {option} is not in the README command reference")


class ExampleOutputTest(unittest.TestCase):
    """examples/bookshop is the full skill output for the bookshop fixture."""

    def test_example_matches_a_fresh_render(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            run_analyzer(FIXTURE, tmp)
            shutil.copy(FIXTURE / "c4-model.json", tmp)
            render_c4.render(tmp, svg=False)
            fresh = {p.name: p.read_text(encoding="utf-8") for p in Path(tmp).glob("*.mmd")}
        committed = {p.name: p.read_text(encoding="utf-8").replace("\r\n", "\n") for p in EXAMPLE.glob("*.mmd")}
        self.assertEqual(sorted(committed), sorted(fresh))
        for name, text in fresh.items():
            self.assertEqual(committed[name], text,
                             f"examples/bookshop/{name} is stale: regenerate it (see examples/README.md)")

    def test_example_has_the_model_and_every_svg(self):
        model = json.loads((EXAMPLE / "c4-model.json").read_text(encoding="utf-8"))
        self.assertEqual(model, json.loads((FIXTURE / "c4-model.json").read_text(encoding="utf-8")))
        for mmd in EXAMPLE.glob("*.mmd"):
            self.assertTrue((EXAMPLE / f"{mmd.stem}.svg").is_file(), f"{mmd.stem}.svg missing")
        report = (EXAMPLE / "ArchitectureReport.md").read_text(encoding="utf-8")
        self.assertIn("![c4-context](c4-context.svg)", report)
        self.assertIn("## Architecture overview", report)


if __name__ == "__main__":
    unittest.main()
