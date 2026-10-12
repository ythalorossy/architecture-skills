"""CLI contract tests: the Python 3.11 guard, file-qualified errors, --debug,
and the c4-facts.json key contract render_c4 checks before it draws anything."""
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "c4-diagrams"
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

ANALYZE = SKILL / "scripts" / "analyze_repository.py"
RENDER = SKILL / "scripts" / "render_c4.py"


def run(script, *args):
    """Run a CLI in a child interpreter; returns (returncode, stdout, stderr)."""
    proc = subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


class CliTest(unittest.TestCase):
    def test_version_guard_exits_1_with_hint(self):
        from scripts import cli_support

        fake = type("version_info", (tuple,), {})((3, 10, 12, "final", 0))

        err = StringIO()
        with mock.patch.object(sys, "version_info", fake), \
                redirect_stderr(err):
            with self.assertRaises(SystemExit) as raised:
                cli_support.require_python()

        self.assertEqual(raised.exception.code, 1)
        message = err.getvalue()
        self.assertIn("Python 3.11+ is required", message)
        self.assertIn("(found 3.10)", message)
        self.assertIn("uv python install 3.12", message)
        self.assertIn("brew install", message)
        self.assertIn("python.org", message)
        # The hint names the two ways to fix it, and stops there.
        self.assertNotIn("Traceback", message)

    def test_render_missing_facts_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty"
            empty.mkdir()

            code, out, err = run(RENDER, str(empty), "--no-svg")

            self.assertEqual(code, 1)
            # The contract is "the error names the file and tells the user
            # what to do" — not the exact path form, which differs between
            # POSIX (``/tmp/...``), Windows (backslash + 8.3 short names on
            # some runners, long form on others), and ``str(Path)`` vs
            # ``Path / "c4-facts.json"`` joining.
            self.assertIn("ERROR:", err)
            self.assertIn("c4-facts.json", err)
            self.assertIn("not found", err)
            self.assertIn("run analyze_repository.py first", err)
            self.assertNotIn("Traceback", err)
            self.assertNotIn("Traceback", out)

    def test_unexpected_error_hint_and_debug(self):
        # Malformed JSON is not the expected "not found" input problem: it is
        # an unexpected failure, so it takes the internal-error path.
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "broken"
            broken.mkdir()
            (broken / "c4-facts.json").write_text("{not json", encoding="utf-8")

            code, out, err = run(RENDER, str(broken), "--no-svg")

            self.assertEqual(code, 1)
            lines = [line for line in err.splitlines() if line.strip()]
            self.assertEqual(len(lines), 1, err)
            self.assertTrue(err.startswith("ERROR: internal error in "), err)
            # module:function, naming this script's own frame, not json internals.
            self.assertIn(":render:", err)
            self.assertIn("(re-run with --debug for the traceback)", err)
            self.assertNotIn("Traceback", err)
            self.assertNotIn("Traceback", out)

            debug_code, debug_out, debug_err = run(
                RENDER, str(broken), "--no-svg", "--debug"
            )

            # --debug changes what is printed, never the exit code.
            self.assertEqual(debug_code, code)
            self.assertIn("ERROR: internal error in ", debug_err)
            self.assertIn("Traceback", debug_err)
            self.assertNotIn("Traceback", debug_out)

        # The same contract holds for the other CLI.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "src").mkdir(parents=True)
            (repo / "src" / "app.js").write_text("export const a = 1;\n")
            out_dir = Path(tmp) / "docs"

            code, out, err = run(
                ANALYZE, str(repo), "--output", str(out_dir), "--debug"
            )
            self.assertEqual(code, 0, err)
            self.assertNotIn("Traceback", err)

            code, out, err = run(
                ANALYZE, str(repo), "--output", str(out_dir), "--debug"
            )
            self.assertEqual(code, 0, err)

    def test_analyze_no_svg_skips_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "src").mkdir(parents=True)
            (repo / "src" / "app.js").write_text("export const a = 1;\n")
            out_dir = Path(tmp) / "docs"

            code, out, err = run(
                ANALYZE, str(repo), "--output", str(out_dir), "--no-svg"
            )
            self.assertEqual(code, 0, err)
            self.assertFalse(any(out_dir.rglob("*.svg")), err)


# Every key render() reads out of c4-facts.json without a default.
REQUIRED_FACTS_KEYS = (
    "containers", "data_stores", "external_systems", "relationships",
    "endpoints", "deployment", "configuration",
)

# A c4-facts.json with every required key present and nothing to draw.
MINIMAL_FACTS = {
    "repository": "demo",
    "containers": [],
    "data_stores": [],
    "external_systems": [],
    "relationships": [],
    "endpoints": [],
    "deployment": {},
    "configuration": {},
}


class FactsKeyContractTest(unittest.TestCase):
    """A c4-facts.json missing a key render() needs is named, not ignored.

    Before this check, dropping `endpoints`, `configuration` or `deployment`
    made render() exit 0 with those report sections silently gone, and
    dropping `data_stores` raised an opaque internal KeyError.
    """

    def _write_facts(self, folder, drop=None):
        facts = dict(MINIMAL_FACTS)
        if drop is not None:
            del facts[drop]
        (folder / "c4-facts.json").write_text(json.dumps(facts), encoding="utf-8")

    def test_complete_facts_render(self):
        from scripts.render_c4 import render

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._write_facts(out)
            self.assertEqual(render(out, svg=False)["status"], "ok")

    def test_every_missing_key_is_reported(self):
        from scripts.cli_support import UserError
        from scripts.render_c4 import render

        for key in REQUIRED_FACTS_KEYS:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                self._write_facts(out, drop=key)
                with self.assertRaises(UserError) as raised:
                    render(out, svg=False)
                self.assertEqual(
                    str(raised.exception),
                    f"c4-facts.json: {key} missing; re-run analyze_repository.py",
                )

    def test_cli_exits_1_without_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._write_facts(out, drop="data_stores")

            code, stdout, err = run(RENDER, str(out), "--no-svg")

            self.assertEqual(code, 1, err)
            self.assertIn(
                "ERROR: c4-facts.json: data_stores missing; re-run analyze_repository.py",
                err,
            )
            self.assertNotIn("internal error", err)
            self.assertNotIn("Traceback", err)
            self.assertNotIn("Traceback", stdout)


if __name__ == "__main__":
    unittest.main()