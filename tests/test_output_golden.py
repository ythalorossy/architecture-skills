"""
Golden tests for the files a user reads: every .mmd diagram and
ArchitectureReport.md.

The facts goldens (test_analyze_e2e) can't see a diagram that lost a box,
merged two nodes or stopped parsing; these can. Each fixture is analyzed
without SVGs, and bookshop also goes through the full skill pipeline (its
reference c4-model.json, then render_c4), which adds the System Context,
the key flow and the Level 4 class diagram.

To accept an intended output change, regenerate and review the diff:

    C4_UPDATE_GOLDEN=1 python3 -m unittest discover -s tests -p test_output_golden.py
"""
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import mask_volatile, run_analyzer

from scripts import render_c4

TESTS = Path(__file__).resolve().parent
FIXTURES_ROOT = TESTS / "fixtures" / "repos"
GOLDEN_ROOT = TESTS / "golden"
UPDATE = os.environ.get("C4_UPDATE_GOLDEN") == "1"

# Analyzer-only fixtures: one per ecosystem, plus the multi-module JVM shape
# that crashed 3.3.2 and the `freight` eval fixture (whose diagrams are the
# only committed proof that its traps still look the way the gold expects).
FIXTURES = [
    "dotnet_sln",
    "maven_multi",
    "maven_layered",
    "gradle_kts",
    "go_mod",
    "node_workspace",
    "python_dist",
    "compose_poly",
    "bookshop",
    "freight",
]


def _outputs(folder):
    """
    {file name: text} for the diagrams and the report, with LF line endings
    and the generator version masked (it changes with every release).
    """
    files = sorted(Path(folder).glob("*.mmd")) + [Path(folder) / "ArchitectureReport.md"]
    return {
        f.name: re.sub(r"Generator Version: \S+", "Generator Version: <version>",
                       f.read_text(encoding="utf-8").replace("\r\n", "\n"))
        for f in files
    }


class OutputGoldenTest(unittest.TestCase):
    maxDiff = None

    def check(self, golden_dir, outputs):
        if UPDATE:
            if golden_dir.exists():
                shutil.rmtree(golden_dir)
            golden_dir.mkdir(parents=True)
            for name, text in outputs.items():
                (golden_dir / name).write_text(text, encoding="utf-8", newline="\n")
            return
        expected = {f.name: f.read_text(encoding="utf-8") for f in sorted(golden_dir.iterdir())}
        self.assertEqual(sorted(outputs), sorted(expected), f"different set of files in {golden_dir.name}")
        for name, text in outputs.items():
            self.assertEqual(text, expected[name], f"{golden_dir.relative_to(GOLDEN_ROOT)}/{name}")

    def test_analyzer_output(self):
        for name in FIXTURES:
            with self.subTest(fixture=name), tempfile.TemporaryDirectory() as tmp:
                run_analyzer(FIXTURES_ROOT / name, tmp)
                self.check(GOLDEN_ROOT / name / "output", _outputs(tmp))

    def test_full_pipeline_with_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_analyzer(FIXTURES_ROOT / "bookshop", tmp)
            shutil.copy(FIXTURES_ROOT / "bookshop" / "c4-model.json", tmp)
            result = render_c4.render(tmp, svg=False)
            self.assertEqual(result["status"], "ok", result)
            outputs = _outputs(tmp)
        for stem in ("c4-context", "c4-flow-place-order", "c4-code-bookshop-api-bookshop-orders"):
            self.assertIn(f"{stem}.mmd", outputs)
        self.check(GOLDEN_ROOT / "bookshop" / "with-model", outputs)


class MavenLayeredTest(unittest.TestCase):
    """3.3.2 crashed on this shape: a module's walk returned a sibling's files."""

    def test_layered_spring_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            facts, summary = run_analyzer(FIXTURES_ROOT / "maven_layered", tmp)
        self.assertEqual(summary["status"], "ok")
        # Only the module with a main class runs on its own; the others are libraries.
        self.assertEqual([(c["name"], c["technology"]) for c in facts["containers"]],
                         [("shop-api", "Spring Boot")])
        self.assertEqual([d["name"] for d in facts["data_stores"]], ["Redis"])
        if UPDATE:
            golden = GOLDEN_ROOT / "maven_layered"
            golden.mkdir(parents=True, exist_ok=True)
            for file_name, data in (("c4-facts.json", facts), ("summary.json", summary)):
                (golden / file_name).write_text(json.dumps(mask_volatile(data), indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
