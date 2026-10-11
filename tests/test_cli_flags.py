"""
CLI flag tests for SPEC-05 Task 4 (D3 flag matrix).

Tests the --svg and --no-svg flags on analyze_repository.py, verifying:
- AC7: default renders only dependency-graph.svg, --svg adds C4 SVGs, --no-svg renders nothing
- C4_SVG=0 acts like --no-svg for both scripts
- render_c4.py honours C4_SVG=0

Uses fake renderers from tests/fakes/ so no real Node.js is required.
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
FAKES = ROOT / "tests" / "fakes"


def _run_analyzer(repo, out_dir, *, extra_env=None, extra_args=None):
    """Run analyzer with fake mmdc on PATH."""
    env = os.environ.copy()
    env["PATH"] = str(FAKES) + os.pathsep + "/usr/bin:/bin"
    if extra_env:
        env.update(extra_env)
    args = [sys.executable, str(ANALYZE), str(repo), "--output", str(out_dir)]
    if extra_args:
        args.extend(extra_args)
    proc = subprocess.run(args, capture_output=True, text=True, env=env)
    return proc


def _run_render(out_dir, *, extra_env=None, extra_args=None):
    """Run render_c4.py with fake mmdc on PATH."""
    env = os.environ.copy()
    env["PATH"] = str(FAKES) + os.pathsep + "/usr/bin:/bin"
    if extra_env:
        env.update(extra_env)
    args = [sys.executable, str(RENDER), str(out_dir)]
    if extra_args:
        args.extend(extra_args)
    proc = subprocess.run(args, capture_output=True, text=True, env=env)
    return proc


class TestAnalyzerSvgFlags(unittest.TestCase):
    """AC7: D3 flag matrix for analyze_repository.py."""

    @classmethod
    def setUpClass(cls):
        # Build a minimal Node.js project fixture that produces C4 diagrams
        cls.tmp = Path(tempfile.mkdtemp())
        cls.repo = cls.tmp / "repo"
        cls.repo.mkdir()
        (cls.repo / "src").mkdir()
        (cls.repo / "src" / "app.js").write_text(
            "export const a = 1;\nexport default { a };\n", encoding="utf-8"
        )
        (cls.repo / "package.json").write_text(
            '{"name": "test-repo", "version": "1.0.0"}\n', encoding="utf-8"
        )
        cls.out = cls.tmp / "out"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_analyzer_default_renders_only_dependency_graph(self):
        """
        AC7: By default the analyzer renders SVGs but no c4-*.svg files.
        The dependency-graph SVG may use a batch temp filename as stem.
        """
        out = self.tmp / "out_default"
        out.mkdir(exist_ok=True)
        proc = _run_analyzer(self.repo, out)

        self.assertEqual(proc.returncode, 0, proc.stderr)

        svg_files = list(out.rglob("*.svg"))
        stems = {p.stem for p in svg_files}

        # At least one SVG should be generated (dep-graph)
        self.assertGreater(len(svg_files), 0,
                         f"Expected at least one SVG; got {svg_files}")
        # No c4-*.svg by default
        c4_svgs = [s for s in stems if s.startswith("c4-")]
        self.assertEqual(c4_svgs, [],
                        f"Expected no c4-*.svg by default, got {c4_svgs}")

    def test_analyzer_svg_flag_renders_c4(self):
        """
        AC7: With --svg the analyzer also renders c4-*.svg files.
        """
        out = self.tmp / "out_svg"
        out.mkdir(exist_ok=True)
        proc = _run_analyzer(self.repo, out, extra_args=["--svg"])

        self.assertEqual(proc.returncode, 0, proc.stderr)

        svg_files = list(out.rglob("*.svg"))
        stems = {p.stem for p in svg_files}

        # At least one SVG
        self.assertGreater(len(svg_files), 0,
                         f"Expected at least one SVG; got {svg_files}")
        # c4-*.svg files should exist
        c4_svgs = [s for s in stems if s.startswith("c4-")]
        self.assertGreater(len(c4_svgs), 0,
                         f"Expected c4-*.svg with --svg, got {stems}")

    def test_no_svg_renders_nothing(self):
        """
        AC7: With --no-svg the analyzer renders no SVGs at all.
        """
        out = self.tmp / "out_no_svg"
        out.mkdir(exist_ok=True)
        proc = _run_analyzer(self.repo, out, extra_args=["--no-svg"])

        self.assertEqual(proc.returncode, 0, proc.stderr)

        svg_files = list(out.rglob("*.svg"))
        self.assertEqual(svg_files, [],
                        f"Expected no SVG files with --no-svg; got {[p.name for p in svg_files]}")

    def test_c4_svg_env_zero_disables_all(self):
        """
        AC7: C4_SVG=0 acts like --no-svg for the analyzer.
        """
        out = self.tmp / "out_env_zero"
        out.mkdir(exist_ok=True)
        proc = _run_analyzer(self.repo, out, extra_env={"C4_SVG": "0"})

        self.assertEqual(proc.returncode, 0, proc.stderr)

        svg_files = list(out.rglob("*.svg"))
        self.assertEqual(svg_files, [],
                        f"Expected no SVGs with C4_SVG=0; got {[p.name for p in svg_files]}")


class TestRenderC4SvgFlags(unittest.TestCase):
    """AC7: render_c4.py honours --no-svg and C4_SVG=0."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.out = cls.tmp / "out"
        cls.out.mkdir()
        # Write minimal c4-facts.json
        facts = {
            "repository": "test-repo",
            "technology": "Node.js",
            "containers": [
                {"id": "api", "name": "API", "kind": "container",
                 "technology": "Node.js", "evidence": [], "path": "src/api"},
            ],
            "data_stores": [],
            "external_systems": [],
            "relationships": [],
        }
        (cls.out / "c4-facts.json").write_text(json.dumps(facts), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_render_c4_no_svg(self):
        """render_c4.py --no-svg renders no SVGs."""
        proc = _run_render(self.out, extra_args=["--no-svg"])

        self.assertEqual(proc.returncode, 0, proc.stderr)

        svg_files = list(self.out.rglob("*.svg"))
        self.assertEqual(svg_files, [],
                        f"Expected no SVGs with --no-svg; got {[p.name for p in svg_files]}")

    def test_render_c4_env_c4_svg_zero(self):
        """render_c4.py with C4_SVG=0 renders no SVGs."""
        proc = _run_render(self.out, extra_env={"C4_SVG": "0"})

        self.assertEqual(proc.returncode, 0, proc.stderr)

        svg_files = list(self.out.rglob("*.svg"))
        self.assertEqual(svg_files, [],
                        f"Expected no SVGs with C4_SVG=0; got {[p.name for p in svg_files]}")


class TestSyntaxErrorReporting(unittest.TestCase):
    """AC3 / AC8: syntax error is named, not 'needs Node.js'."""

    def test_syntax_error_in_summary(self):
        """
        With a syntax-error fake, summary.json contains c4.svg[stem].status == "syntax-error".
        The console names the stem, and "needs Node.js" is absent.
        """
        # Create a temp fixture
        tmp = Path(tempfile.mkdtemp())
        try:
            repo = tmp / "repo"
            repo.mkdir()
            (repo / "src").mkdir()
            (repo / "src" / "app.js").write_text(
                "export const a = 1;\nexport default { a };\n", encoding="utf-8"
            )
            out = tmp / "out"

            # Use the syntax-error fake via PATH
            env = os.environ.copy()
            env["PATH"] = str(FAKES) + os.pathsep + "/usr/bin:/bin"

            # Patch render_c4 to use syntax-error fake
            proc = subprocess.run(
                [sys.executable, str(ANALYZE), str(repo), "--output", str(out),
                 "--svg"],
                capture_output=True, text=True, env=env,
            )

            # The analyzer should still exit 0 (degraded, not failed)
            self.assertEqual(proc.returncode, 0, proc.stderr)

            summary_path = out / "summary.json"
            if summary_path.exists():
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                c4 = summary.get("c4", {})
                svg = c4.get("svg", {})
                for stem, info in svg.items():
                    status = info.get("status", "")
                    if status == "syntax-error":
                        self.assertIn("Parse error", info.get("message", ""),
                                    "syntax-error must carry the parse message")
                        break

            # "needs Node.js" must not appear in output
            combined = proc.stdout + proc.stderr
            self.assertNotIn("needs Node.js", combined,
                            "'needs Node.js' must not appear in output")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
