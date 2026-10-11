"""
Tests for svg_render.py.

The renderer is driven through its public render() function with a fake
mermaid-cli (tests/fakes/fake_mmdc.py) started as a real subprocess, so the
argument passing, timeouts and status classification are exercised end to
end on every platform without Node.js.
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "c4-diagrams"
FAKE_MMDC = ROOT / "tests" / "fakes" / "fake_mmdc.py"

if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from scripts import svg_render as sr  # noqa: E402


class RenderTestCase(unittest.TestCase):
    """Temp dir with N diagrams and a fake renderer selected by mode."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.out = self.tmp / "out"
        self.log = self.tmp / "calls.jsonl"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def stems(self, count):
        result = []
        for i in range(count):
            path = self.tmp / f"stem{i}.mmd"
            path.write_text("flowchart TB\n    a --> b\n", encoding="utf-8")
            result.append((f"stem{i}", path))
        return result

    def render(self, stems, mode="ok", kind="mmdc", extra_env=None):
        env = {"FAKE_MMDC_MODE": mode, "FAKE_MMDC_LOG": str(self.log)}
        env.update(extra_env or {})
        command = [sys.executable, str(FAKE_MMDC)]
        with mock.patch.object(sr, "_resolve", return_value=(kind, command)), \
                mock.patch.dict(os.environ, env):
            return sr.render(stems, self.out)

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]


class TestOk(RenderTestCase):
    def test_every_diagram_rendered_once(self):
        results = self.render(self.stems(5))

        self.assertEqual([r.stem for r in results], [f"stem{i}" for i in range(5)])
        self.assertEqual({r.status for r in results}, {"ok"})
        for i in range(5):
            self.assertTrue((self.out / f"stem{i}.svg").is_file())
        # One process per diagram, each told to write its own .svg file.
        calls = self.calls()
        self.assertEqual(len(calls), 5)
        self.assertEqual(sorted(Path(c["output"]).name for c in calls),
                         [f"stem{i}.svg" for i in range(5)])

    def test_exit_0_without_svg_is_a_tool_error(self):
        results = self.render(self.stems(1), mode="no-output")
        self.assertEqual(results[0].status, "tool-error")

    def test_no_stems(self):
        self.assertEqual(self.render([]), [])


class TestSyntaxError(RenderTestCase):
    def test_parse_error_is_reported_per_diagram(self):
        results = self.render(self.stems(3), mode="syntax")

        self.assertEqual({r.status for r in results}, {"syntax-error"})
        self.assertIn("Parse error on line 9", results[0].message)
        # A syntax error is the diagram's fault, not the renderer's: every
        # diagram is still tried.
        self.assertEqual(len(self.calls()), 3)


class TestTimeout(RenderTestCase):
    def test_hang_times_out_and_skips_the_rest(self):
        pid_file = self.tmp / "child.pid"
        with mock.patch.object(sr, "_TIMEOUT_PER_DIAGRAM", 2):
            start = time.monotonic()
            results = self.render(self.stems(4), mode="hang",
                                  extra_env={"FAKE_MMDC_PID_FILE": str(pid_file)})
            elapsed = time.monotonic() - start

        self.assertEqual(results[0].status, "timeout")
        self.assertIn("timed out", results[0].message)
        self.assertEqual([r.status for r in results[1:]], ["skipped"] * 3)
        self.assertLess(elapsed, 15, "remaining diagrams must not each wait out a timeout")
        self.assertEqual(len(self.calls()), 1)

    @unittest.skipIf(os.name == "nt", "process-group check uses POSIX signals")
    def test_timeout_kills_the_whole_process_tree(self):
        pid_file = self.tmp / "child.pid"
        with mock.patch.object(sr, "_TIMEOUT_PER_DIAGRAM", 2):
            self.render(self.stems(1), mode="hang",
                        extra_env={"FAKE_MMDC_PID_FILE": str(pid_file)})

        child = int(pid_file.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                return
            # A killed child that hasn't been reaped yet shows as a zombie.
            try:
                with open(f"/proc/{child}/stat", encoding="utf-8") as fh:
                    if fh.read().split()[2] == "Z":
                        return
            except OSError:
                pass
            time.sleep(0.1)
        self.fail(f"grandchild {child} survived the timeout")


class TestStartFailure(RenderTestCase):
    def test_renderer_that_cannot_start_skips_the_rest(self):
        missing = self.tmp / "no-such-renderer"
        with mock.patch.object(sr, "_resolve", return_value=("mmdc", [str(missing)])):
            results = sr.render(self.stems(3), self.out)

        self.assertEqual(results[0].status, "tool-error")
        self.assertIn("could not start", results[0].message)
        self.assertEqual([r.status for r in results[1:]], ["skipped"] * 2)


class TestNpxCache(RenderTestCase):
    def test_enotcached_retries_online_once_then_uses_the_cache(self):
        results = self.render(self.stems(3), mode="enotcached", kind="npx")

        self.assertEqual({r.status for r in results}, {"ok"})
        offline_flags = [c["offline"] for c in self.calls()]
        # Each diagram tries the cache first; this fake never fills the
        # cache, so each gets exactly one online retry.
        self.assertEqual(offline_flags.count(False), 3)
        self.assertEqual(offline_flags.count(True), 3)

    def test_mmdc_never_runs_offline(self):
        self.render(self.stems(2), mode="enotcached", kind="mmdc")
        self.assertEqual([c["offline"] for c in self.calls()], [False, False])


class TestResolve(unittest.TestCase):
    def test_missing_tool_is_immediate(self):
        with tempfile.TemporaryDirectory() as tmp:
            mmd = Path(tmp) / "a.mmd"
            mmd.write_text("flowchart TB\n", encoding="utf-8")
            with mock.patch.object(sr.shutil, "which", return_value=None):
                start = time.monotonic()
                results = sr.render([("a", mmd), ("b", mmd)], Path(tmp) / "out")
        self.assertLess(time.monotonic() - start, 1.0)
        self.assertEqual({r.status for r in results}, {"missing-tool"})

    def test_prefers_mmdc(self):
        with mock.patch.object(sr.shutil, "which", side_effect=lambda name: f"/bin/{name}"):
            self.assertEqual(sr._resolve(), ("mmdc", ["/bin/mmdc"]))

    def test_npx_uses_the_pinned_version(self):
        with mock.patch.object(sr.shutil, "which",
                               side_effect=lambda name: "/bin/npx" if name == "npx" else None):
            kind, command = sr._resolve()
        self.assertEqual(kind, "npx")
        self.assertEqual(command, ["/bin/npx", "-y", f"@mermaid-js/mermaid-cli@{sr.MERMAID_CLI_VERSION}"])


class TestDisabled(unittest.TestCase):
    def test_svg_flag_false_and_env_disabled_skip_everything(self):
        stems = [("a", Path("a.mmd")), ("b", Path("b.mmd"))]
        for kwargs in ({"svg_flag": False}, {"env_disabled": True}):
            results = sr.render(stems, Path("unused"), **kwargs)
            self.assertEqual({r.status for r in results}, {"skipped"}, kwargs)


class TestConfig(unittest.TestCase):
    def test_config_uses_a_system_font_and_plain_text_labels(self):
        path = sr._write_config()
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        finally:
            path.unlink()
        self.assertFalse(config["htmlLabels"])
        self.assertFalse(config["flowchart"]["htmlLabels"])
        self.assertIn("arial", config["themeVariables"]["fontFamily"])


@unittest.skipUnless(os.environ.get("C4_REAL_RENDER") == "1",
                     "set C4_REAL_RENDER=1 to render with the real mermaid-cli")
class TestRealRenderer(unittest.TestCase):
    """Opt-in: the pinned mermaid-cli renders a C4-style flowchart."""

    def test_real_mermaid_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            mmd = Path(tmp) / "c4.mmd"
            mmd.write_text(
                "---\nconfig:\n  layout: elk\n---\nflowchart TB\n"
                '    subgraph boundary["`**Shop** [Software System]`"]\n'
                '        api["`**API**\n[Container]`"]\n    end\n'
                '    user["`**User**`"] -->|"`Uses`"| api\n',
                encoding="utf-8",
            )
            results = sr.render([("c4", mmd)], Path(tmp))
            self.assertEqual(results[0].status, "ok", results[0])
            svg = (Path(tmp) / "c4.svg").read_text(encoding="utf-8")
        self.assertNotIn("@font-face", svg)
        self.assertLess(len(svg.encode("utf-8")), 100_000)


if __name__ == "__main__":
    unittest.main()
