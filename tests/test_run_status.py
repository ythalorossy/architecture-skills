"""
What makes a run `degraded`, and what --strict does about it.

Degraded means the user should look at something: a file that could not be
read or parsed, a diagram that failed to render, or an invalid
c4-model.json. Each cause is listed in summary.json `warnings`. A machine
without Node.js is not degraded: SVGs are optional, so it gets one note.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import REPO_ROOT

from scripts import svg_render
from scripts.analyze_repository import RepositoryAnalyzer

BOOKSHOP = REPO_ROOT / "tests" / "fixtures" / "repos" / "bookshop"
ANALYZE = REPO_ROOT / "skills" / "c4-diagrams" / "scripts" / "analyze_repository.py"
FAKE_MMDC = REPO_ROOT / "tests" / "fakes" / "fake_mmdc.py"

INVALID_MODEL = {
    "system": {"name": "Bookshop", "description": "Sells books"},
    "relationships": [{"from": "ghost", "to": "nothing", "description": "Calls"}],
}


class RunStatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.out = self.tmp / "out"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def analyze(self, **env):
        """Run the analyzer in-process with rendering on; return (summary, stdout)."""
        stdout = io.StringIO()
        with mock.patch.dict(os.environ, {"C4_SVG": "1", **env}), contextlib.redirect_stdout(stdout):
            RepositoryAnalyzer(str(BOOKSHOP), str(self.out)).run()
        summary = json.loads((self.out / "summary.json").read_text(encoding="utf-8"))
        return summary, stdout.getvalue()

    def test_no_renderer_is_ok_with_a_note(self):
        with mock.patch.object(svg_render.shutil, "which", return_value=None):
            summary, stdout = self.analyze()

        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["warnings"], [])
        self.assertIn("NOTE: SVGs not rendered", stdout)
        self.assertNotIn("DEGRADED", stdout)
        self.assertEqual(summary["c4"]["svg"]["dependency-graph"]["status"], "missing-tool")

    def test_render_failure_is_degraded_and_listed(self):
        fake = mock.patch.object(svg_render, "_resolve",
                                 return_value=("mmdc", [sys.executable, str(FAKE_MMDC)]))
        with fake:
            summary, stdout = self.analyze(FAKE_MMDC_MODE="syntax")

        self.assertEqual(summary["status"], "degraded")
        render = [w for w in summary["warnings"] if w["kind"] == "render"]
        self.assertIn("c4-container.mmd", {w["path"] for w in render})
        self.assertTrue(all("syntax-error" in w["message"] for w in render))
        self.assertIn("DEGRADED: ", stdout)

    def test_all_rendered_is_ok(self):
        fake = mock.patch.object(svg_render, "_resolve",
                                 return_value=("mmdc", [sys.executable, str(FAKE_MMDC)]))
        with fake:
            summary, _ = self.analyze()
        self.assertEqual(summary["status"], "ok")
        self.assertEqual({info["status"] for info in summary["c4"]["svg"].values()}, {"ok"})


class StrictExitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.out = self.tmp / "out"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args, env=None):
        full_env = {**os.environ, **(env or {})}
        return subprocess.run([sys.executable, str(ANALYZE), str(BOOKSHOP), "--output", str(self.out), *args],
                              capture_output=True, text=True, env=full_env)

    def test_invalid_model_is_degraded_and_strict_exits_2(self):
        self.out.mkdir()
        (self.out / "c4-model.json").write_text(json.dumps(INVALID_MODEL), encoding="utf-8")

        lenient = self.run_cli("--no-svg")
        self.assertEqual(lenient.returncode, 0, lenient.stderr)
        summary = json.loads((self.out / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "degraded")
        self.assertEqual(summary["c4"]["model_status"], "invalid")

        strict = self.run_cli("--no-svg", "--strict")
        self.assertEqual(strict.returncode, 2, strict.stdout + strict.stderr)

    def test_missing_node_with_strict_exits_0(self):
        # An empty PATH entry list: neither mmdc nor npx can be found.
        empty = self.tmp / "empty-bin"
        empty.mkdir()
        proc = self.run_cli("--strict", env={"C4_SVG": "1", "PATH": str(empty)})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("NOTE: SVGs not rendered", proc.stdout)


if __name__ == "__main__":
    unittest.main()
