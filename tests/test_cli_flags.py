"""
SVG switches of analyze_repository.py and render_c4.py.

- By default the analyzer renders every diagram to SVG: the dependency graph
  and the C4 diagrams.
- --no-svg, or C4_SVG=0 in the environment, renders none.
- --svg is still accepted (it was needed in 3.3.0-3.3.2) and changes nothing.

Rendering runs through a fake mermaid-cli (tests/fakes/fake_mmdc.py), so no
Node.js is needed.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import write

from scripts import svg_render
from scripts.analyze_repository import RepositoryAnalyzer

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "c4-diagrams"
ANALYZE = SKILL / "scripts" / "analyze_repository.py"
RENDER = SKILL / "scripts" / "render_c4.py"
FAKE_MMDC = ROOT / "tests" / "fakes" / "fake_mmdc.py"


def _fake_renderer(mode="ok"):
    """Patch svg_render to use the fake mermaid-cli, with rendering enabled."""
    resolve = mock.patch.object(svg_render, "_resolve",
                                return_value=("mmdc", [sys.executable, str(FAKE_MMDC)]))
    env = mock.patch.dict(os.environ, {"FAKE_MMDC_MODE": mode, "C4_SVG": "1"})
    return resolve, env


def _run(script, *args, env=None):
    full_env = os.environ.copy()
    full_env.update(env or {})
    return subprocess.run([sys.executable, str(script), *map(str, args)],
                          capture_output=True, text=True, env=full_env)


def _svgs(folder):
    return sorted(p.name for p in Path(folder).rglob("*.svg"))


class AnalyzerFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.repo = cls.tmp / "repo"
        write(cls.repo, {
            "package.json": '{"name": "shop", "version": "1.0.0", "dependencies": {"express": "4", "pg": "8"}}\n',
            "src/server.js": "import pg from 'pg';\nimport { cart } from './cart/index.js';\n",
            "src/cart/index.js": "export const cart = 1;\n",
        })

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


class TestAnalyzerSvgDefaults(AnalyzerFixture):
    def test_default_renders_dependency_graph_and_c4_svgs(self):
        out = self.tmp / "default"
        resolve, env = _fake_renderer()
        with resolve, env:
            RepositoryAnalyzer(str(self.repo), str(out)).run()

        svgs = _svgs(out)
        self.assertIn("dependency-graph.svg", svgs)
        self.assertIn("c4-container.svg", svgs)
        # Every diagram that has Mermaid source also has its SVG.
        for mmd in out.glob("*.mmd"):
            self.assertIn(f"{mmd.stem}.svg", svgs)
        report = (out / "ArchitectureReport.md").read_text(encoding="utf-8")
        self.assertIn("![c4-container](c4-container.svg)", report)

    def test_no_svg_renders_nothing(self):
        out = self.tmp / "no-svg"
        resolve, env = _fake_renderer()
        with resolve, env:
            RepositoryAnalyzer(str(self.repo), str(out), no_svg=True).run()
        self.assertEqual(_svgs(out), [])

    def test_c4_svg_0_renders_nothing(self):
        out = self.tmp / "env-off"
        resolve, env = _fake_renderer()
        with resolve, env, mock.patch.dict(os.environ, {"C4_SVG": "0"}):
            RepositoryAnalyzer(str(self.repo), str(out)).run()
        self.assertEqual(_svgs(out), [])

    def test_syntax_error_is_recorded_per_diagram(self):
        out = self.tmp / "syntax"
        resolve, env = _fake_renderer("syntax")
        with resolve, env:
            RepositoryAnalyzer(str(self.repo), str(out)).run()

        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        svg = summary["c4"]["svg"]
        self.assertEqual(svg["c4-container"]["status"], "syntax-error")
        self.assertIn("Parse error", svg["c4-container"]["message"])


class TestAnalyzerCli(AnalyzerFixture):
    def test_cli_no_svg_and_env(self):
        for args, env in ((["--no-svg"], {}), ([], {"C4_SVG": "0"})):
            out = self.tmp / f"cli-{len(args)}"
            proc = _run(ANALYZE, self.repo, "--output", out, *args, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(_svgs(out), [], (args, env))

    def test_legacy_svg_flag_is_accepted(self):
        out = self.tmp / "cli-legacy"
        proc = _run(ANALYZE, self.repo, "--output", out, "--svg", env={"C4_SVG": "0"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("--svg", _run(ANALYZE, "--help").stdout)


class TestRenderC4Switches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.out = cls.tmp / "out"
        cls.out.mkdir()
        facts = {
            "repository": "shop",
            "containers": [{"id": "api", "name": "API", "kind": "container", "technology": "Node.js",
                            "evidence": [], "path": "src"}],
            "data_stores": [], "external_systems": [], "relationships": [],
        }
        (cls.out / "c4-facts.json").write_text(json.dumps(facts), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_no_svg_and_env_render_nothing(self):
        for args, env in ((["--no-svg"], {}), ([], {"C4_SVG": "0"})):
            proc = _run(RENDER, self.out, *args, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(_svgs(self.out), [], (args, env))


if __name__ == "__main__":
    unittest.main()
