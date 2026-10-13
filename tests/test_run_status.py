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


class RunDiagnosticsTest(unittest.TestCase):
    """What the run tells the user about files it skipped and diagrams it could not draw."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = self.tmp / "repo"
        shutil.copytree(BOOKSHOP, self.repo)
        self.out = self.tmp / "out"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def analyze(self, **env):
        stdout = io.StringIO()
        with mock.patch.dict(os.environ, {"C4_SVG": "0", **env}), contextlib.redirect_stdout(stdout):
            RepositoryAnalyzer(str(self.repo), str(self.out), no_svg=env.get("C4_SVG") != "1").run()
        summary = json.loads((self.out / "summary.json").read_text(encoding="utf-8"))
        return summary, stdout.getvalue()

    def _write_oversized(self, relative):
        """A file past MAX_TEXT_BYTES, shaped like the generated bundles the cap is for."""
        from scripts.repo_index import MAX_TEXT_BYTES
        path = self.repo / relative
        path.write_text("# padding\n" * (MAX_TEXT_BYTES // 10 + 100), encoding="utf-8")
        return path

    def test_a_source_file_too_large_to_read_is_reported(self):
        """Dropped silently before: the facts are collected without it and nothing says so."""
        self._write_oversized("api/bookshop/orders/generated.py")

        summary, _ = self.analyze()

        skipped = {entry["path"]: entry["reason"] for entry in summary["skipped_files"]}
        self.assertIn("api/bookshop/orders/generated.py", skipped, summary["skipped_files"])
        self.assertEqual(skipped["api/bookshop/orders/generated.py"], "too_large")

    def test_a_module_too_large_to_read_does_not_stop_the_run(self):
        """A top-level module is its own project, and its text was used unchecked."""
        self._write_oversized("api/bookshop/generated.py")

        summary, _ = self.analyze()

        self.assertEqual(summary["repository"], "repo")
        self.assertIn("api/bookshop/generated.py",
                      {entry["path"] for entry in summary["skipped_files"]})

    def test_a_skipped_file_is_named_relative_to_the_repository(self):
        self._write_oversized("api/bookshop/orders/generated.py")

        summary, _ = self.analyze()

        for entry in summary["skipped_files"]:
            self.assertFalse(Path(entry["path"]).is_absolute(), entry)
        for warning in summary["warnings"]:
            self.assertFalse(Path(warning.get("path") or "").is_absolute(), warning)

    def test_drift_is_printed(self):
        self.out.mkdir()
        shutil.copy(BOOKSHOP / "c4-model.json", self.out / "c4-model.json")
        (self.repo / "api" / "bookshop" / "cache.py").write_text(
            "import redis\nclient = redis.Redis()\n", encoding="utf-8")

        summary, stdout = self.analyze()

        self.assertEqual(summary["c4"]["model_status"], "drift")
        self.assertTrue(any(line.startswith("DRIFT: ") for line in stdout.splitlines()), stdout)

    def test_a_diagram_that_failed_to_render_says_so_in_the_report(self):
        fake = mock.patch.object(svg_render, "_resolve",
                                 return_value=("mmdc", [sys.executable, str(FAKE_MMDC)]))
        with fake:
            summary, _ = self.analyze(C4_SVG="1", FAKE_MMDC_MODE="syntax")

        self.assertEqual(summary["status"], "degraded")
        report = (self.out / "ArchitectureReport.md").read_text(encoding="utf-8")
        self.assertIn("did not render", report)

    def test_a_machine_without_a_renderer_gets_no_per_diagram_note(self):
        with mock.patch.object(svg_render.shutil, "which", return_value=None):
            summary, _ = self.analyze(C4_SVG="1")

        self.assertEqual(summary["status"], "ok")
        report = (self.out / "ArchitectureReport.md").read_text(encoding="utf-8")
        self.assertNotIn("did not render", report)


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


class UnreadableOnAnyPlatformTest(unittest.TestCase):
    """What a refused read does to the run, on Windows as well as POSIX.

    test_failure_modes.py proves this against a real mode-000 directory, which
    needs `chmod` and so skips on Windows — where more than half the supported
    CI matrix runs, and where a locked file is the commonest way to meet this.
    These raise the same errors at the I/O boundary instead of at the
    filesystem, so the handling is covered on every platform.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = self.tmp / "repo"
        shutil.copytree(BOOKSHOP, self.repo)
        self.out = self.tmp / "out"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def analyze(self):
        stdout = io.StringIO()
        with mock.patch.dict(os.environ, {"C4_SVG": "0"}), contextlib.redirect_stdout(stdout):
            RepositoryAnalyzer(str(self.repo), str(self.out), no_svg=True).run()
        return json.loads((self.out / "summary.json").read_text(encoding="utf-8"))

    def test_a_file_the_os_refuses_to_open_is_named_and_the_run_finishes(self):
        real_read_text = Path.read_text

        def refuse_one(path_self, *args, **kwargs):
            if path_self.name == "pyproject.toml" and "api" in path_self.parts:
                raise PermissionError(13, "Permission denied")
            return real_read_text(path_self, *args, **kwargs)

        with mock.patch.object(Path, "read_text", refuse_one):
            summary = self.analyze()

        skipped = {entry["path"]: entry["reason"] for entry in summary["skipped_files"]}
        self.assertIn("api/pyproject.toml", skipped, summary["skipped_files"])
        self.assertTrue(skipped["api/pyproject.toml"].startswith("oserror:"), skipped)
        # The reason carries the OS message, not the absolute path again.
        self.assertIn("Permission denied", skipped["api/pyproject.toml"])
        self.assertEqual(summary["status"], "degraded")

    def test_a_directory_the_os_refuses_to_walk_is_named_and_the_run_finishes(self):
        blocked = self.repo / "api" / "bookshop" / "orders"
        real_walk = os.walk

        def refuse_one(top, *args, **kwargs):
            onerror = kwargs.get("onerror")
            if onerror is not None:
                failure = PermissionError(13, "Permission denied")
                failure.filename = str(blocked)
                onerror(failure)
            return real_walk(top, *args, **kwargs)

        with mock.patch.object(os, "walk", refuse_one):
            summary = self.analyze()

        skipped = {entry["path"]: entry["reason"] for entry in summary["skipped_files"]}
        self.assertIn("api/bookshop/orders", skipped, summary["skipped_files"])
        self.assertEqual(skipped["api/bookshop/orders"], "permission")
        self.assertEqual(summary["status"], "degraded")


if __name__ == "__main__":
    unittest.main()
