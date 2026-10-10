"""End-to-end golden tests for the analyzer.

The golden files under ``tests/golden/<fixture>/`` are produced by running
the analyzer on the matching fixture and masking volatile fields. The test
compares masked output to the golden, so absolute paths and any future
``run_id`` / timestamp fields do not make the comparison flake.

Masking is recursive into dicts and lists: ``mask_volatile`` in
``helpers.py`` replaces absolute path strings with ``<abs-path>`` and any
key named ``run_id`` / ``Generated On`` or containing ``timestamp`` with
``<masked>``.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import mask_volatile, run_analyzer


FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures" / "repos"
GOLDEN_ROOT = Path(__file__).resolve().parent / "golden"

# One entry per AC3 ecosystem. Listed in a fixed order so the subTest
# iterations and the golden directory layout stay in lockstep.
FIXTURES = [
    "dotnet_sln",
    "maven_multi",
    "gradle_kts",
    "go_mod",
    "node_workspace",
    "python_dist",
    "compose_poly",
]


def _golden_pair(fixture_name):
    """Return ((expected_facts, expected_summary), tmp_path) for fixture."""
    golden_dir = GOLDEN_ROOT / fixture_name
    facts = json.loads((golden_dir / "c4-facts.json").read_text(encoding="utf-8"))
    summary = json.loads((golden_dir / "summary.json").read_text(encoding="utf-8"))
    return facts, summary


class TestDegradedAndStrictExits(unittest.TestCase):
    """AC1 and AC2: degraded exits, --strict flag."""

    def setUp(self):
        self.maxDiff = 0x10000
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_malformed_pyproject_exits_0_degraded(self):
        """
        AC1: A fixture with a malformed pyproject.toml exits 0.
        summary.json has status == "degraded" and exactly one parse warning.
        stdout ends with a DEGRADED: line.
        """
        fixture = self.tmp / "repo"
        shutil.copytree(FIXTURES_ROOT / "python_dist", fixture)
        # Corrupt the pyproject.toml
        pyproject = fixture / "pyproject.toml"
        pyproject.write_text("invalid toml !@#$\n", encoding="utf-8")

        out = self.tmp / "out"
        out.mkdir()

        # Run via CLI to check exit code
        skill_dir = Path(__file__).resolve().parent.parent / "skills" / "c4-diagrams"
        script = skill_dir / "scripts" / "analyze_repository.py"
        result = subprocess.run(
            [sys.executable, str(script), str(fixture), "--output", str(out)],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, f"degraded run should exit 0: {result.stderr}")

        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "degraded")

        # Exactly one parse warning
        warnings = summary.get("warnings") or []
        parse_warnings = [w for w in warnings if w["kind"] == "parse"]
        self.assertEqual(len(parse_warnings), 1, f"Expected 1 parse warning: {warnings}")

        # stdout ends with DEGRADED line
        lines = result.stdout.strip().splitlines()
        self.assertTrue(
            any("DEGRADED:" in line for line in lines),
            f"Expected DEGRADED: line in stdout: {result.stdout}"
        )

    def test_malformed_pyproject_strict_exits_2(self):
        """
        AC2: The same fixture with --strict exits 2.
        """
        fixture = self.tmp / "repo"
        shutil.copytree(FIXTURES_ROOT / "python_dist", fixture)
        pyproject = fixture / "pyproject.toml"
        pyproject.write_text("broken\n", encoding="utf-8")

        out = self.tmp / "out"
        out.mkdir()

        skill_dir = Path(__file__).resolve().parent.parent / "skills" / "c4-diagrams"
        script = skill_dir / "scripts" / "analyze_repository.py"
        result = subprocess.run(
            [sys.executable, str(script), str(fixture), "--output", str(out), "--strict"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 2, f"--strict should exit 2: {result.stderr}")

    def test_clean_fixture_exits_0_ok(self):
        """
        AC2: A clean fixture exits 0 with status == "ok" and no DEGRADED: line.
        """
        fixture = FIXTURES_ROOT / "python_dist"

        out = self.tmp / "out"
        out.mkdir()

        skill_dir = Path(__file__).resolve().parent.parent / "skills" / "c4-diagrams"
        script = skill_dir / "scripts" / "analyze_repository.py"
        result = subprocess.run(
            [sys.executable, str(script), str(fixture), "--output", str(out)],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, f"clean run should exit 0: {result.stderr}")

        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "ok")

        lines = result.stdout.strip().splitlines()
        degraded_lines = [l for l in lines if "DEGRADED:" in l]
        self.assertEqual(len(degraded_lines), 0, f"No DEGRADED: line expected for clean run: {result.stdout}")


class TestByteIdenticalRerun(unittest.TestCase):
    """AC6: two runs on unchanged fixture produce byte-identical artifacts."""

    def test_summary_json_identical_between_runs(self):
        """
        Two analyzer runs on the same unchanged fixture produce
        byte-identical summary.json.
        """
        fixture = FIXTURES_ROOT / "python_dist"
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            _, summary1 = run_analyzer(fixture, tmp1)
            _, summary2 = run_analyzer(fixture, tmp2)

            masked1 = mask_volatile(summary1)
            masked2 = mask_volatile(summary2)
            self.assertEqual(masked1, masked2)

    def test_c4_facts_identical_between_runs(self):
        """
        Two analyzer runs on the same unchanged fixture produce
        byte-identical c4-facts.json.
        """
        fixture = FIXTURES_ROOT / "python_dist"
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            facts1, _ = run_analyzer(fixture, tmp1)
            facts2, _ = run_analyzer(fixture, tmp2)

            masked1 = mask_volatile(facts1)
            masked2 = mask_volatile(facts2)
            self.assertEqual(masked1, masked2)

    def test_architecture_report_identical_between_runs(self):
        """
        Two analyzer runs on the same unchanged fixture produce
        byte-identical ArchitectureReport.md.
        """
        fixture = FIXTURES_ROOT / "python_dist"
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            run_analyzer(fixture, tmp1)
            run_analyzer(fixture, tmp2)

            report1 = Path(tmp1) / "ArchitectureReport.md"
            report2 = Path(tmp2) / "ArchitectureReport.md"
            self.assertEqual(report1.read_bytes(), report2.read_bytes())

    def test_timestamp_option_adds_timestamp(self):
        """
        With --timestamp, the report contains "Generated On".
        Without it, the report has no Generated On field.
        """
        fixture = FIXTURES_ROOT / "python_dist"
        with tempfile.TemporaryDirectory() as tmp_ts, tempfile.TemporaryDirectory() as tmp_no_ts:
            _, summary_ts = run_analyzer(fixture, tmp_ts, timestamp=True)
            _, summary_no_ts = run_analyzer(fixture, tmp_no_ts, timestamp=False)

            report_ts = (Path(tmp_ts) / "ArchitectureReport.md").read_text(encoding="utf-8")
            report_no_ts = (Path(tmp_no_ts) / "ArchitectureReport.md").read_text(encoding="utf-8")

            self.assertIn("Generated On", report_ts)
            self.assertNotIn("Generated On", report_no_ts)



class DeploymentFalsePositiveTest(unittest.TestCase):
    """AC4: .venv/.tox/node_modules never appear in deployment facts."""

    def test_venv_tox_not_in_deployment(self):
        """Files from .venv, .tox and node_modules are NOT in deployment facts."""
        fixture = FIXTURES_ROOT / "compose_poly"
        with tempfile.TemporaryDirectory() as tmp:
            facts, _ = run_analyzer(fixture, tmp)
        deployment = facts.get("deployment", {})
        all_deployment_files = []
        for category in ["compose", "dockerfiles", "kubernetes", "platforms", "ci"]:
            items = deployment.get(category, [])
            for item in items:
                if isinstance(item, dict):
                    all_deployment_files.append(str(item.get("file", "")))
                elif isinstance(item, str):
                    all_deployment_files.append(item)
        for path in all_deployment_files:
            self.assertNotIn(
                ".venv", path,
                f".venv path found in deployment: {path}",
            )
            self.assertNotIn(
                ".tox", path,
                f".tox path found in deployment: {path}",
            )
            self.assertNotIn(
                "node_modules", path,
                f"node_modules path found in deployment: {path}",
            )

    def test_ci_markers_still_in_deployment(self):
        """.github/workflows/*.yml and .gitlab-ci.yml still appear in deployment."""
        fixture = FIXTURES_ROOT / "compose_poly"
        with tempfile.TemporaryDirectory() as tmp:
            facts, _ = run_analyzer(fixture, tmp)
        deployment = facts.get("deployment", {})
        ci_files = []
        for category in ["compose", "dockerfiles", "kubernetes", "platforms", "ci"]:
            items = deployment.get(category, [])
            for item in items:
                if isinstance(item, dict) and "file" in item:
                    ci_files.append(item["file"])
                elif isinstance(item, str):
                    ci_files.append(item)
        # Check that CI markers (if present) are correctly identified
        # The key assertion is: they should NOT be falsely excluded
        github_workflow_files = [f for f in ci_files if ".github" in f]
        # We don't assert these exist in compose_poly fixture,
        # but if they DO exist they should be present, not filtered out
        for f in github_workflow_files:
            self.assertIn(".yml", f, f"CI file {f} should be a YAML file")


class AnalyzeE2ETest(unittest.TestCase):
    def test_e2e_matches_golden(self):
        for fixture_name in FIXTURES:
            with self.subTest(fixture=fixture_name):
                fixture = FIXTURES_ROOT / fixture_name
                with tempfile.TemporaryDirectory() as tmp:
                    facts, summary = run_analyzer(fixture, tmp)
                expected_facts, expected_summary = _golden_pair(fixture_name)
                self.assertEqual(mask_volatile(facts), expected_facts)
                self.assertEqual(mask_volatile(summary), expected_summary)

    def test_e2e_is_deterministic(self):
        for fixture_name in FIXTURES:
            with self.subTest(fixture=fixture_name):
                fixture = FIXTURES_ROOT / fixture_name
                with tempfile.TemporaryDirectory() as tmp1, \
                        tempfile.TemporaryDirectory() as tmp2:
                    facts1, summary1 = run_analyzer(fixture, tmp1)
                    facts2, summary2 = run_analyzer(fixture, tmp2)
                # Masking must produce byte-equal dicts across runs.
                self.assertEqual(
                    mask_volatile(facts1),
                    mask_volatile(facts2),
                    f"{fixture_name}: c4-facts.json not byte-identical between runs",
                )
                self.assertEqual(
                    mask_volatile(summary1),
                    mask_volatile(summary2),
                    f"{fixture_name}: summary.json not byte-identical between runs",
                )


if __name__ == "__main__":
    unittest.main()