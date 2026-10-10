"""Tests for diagnostics.py – SPEC-08 diagnostics collector."""
import unittest

import sys
from pathlib import Path

# Ensure the skill scripts are on the path
REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "c4-diagrams"
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from scripts.diagnostics import DiagnosticsCollector, Diagnostic


class TestDiagnosticDedup(unittest.TestCase):
    """Collector deduplicates identical diagnostics."""

    def test_same_diagnostic_reported_twice_appears_once(self):
        c = DiagnosticsCollector()
        c.parse_error("python_projects", "api/pyproject.toml", "invalid TOML: ...")
        c.parse_error("python_projects", "api/pyproject.toml", "invalid TOML: ...")
        self.assertEqual(len(c.warnings()), 1)

    def test_different_paths_are_kept(self):
        c = DiagnosticsCollector()
        c.parse_error("python_projects", "api/pyproject.toml", "invalid TOML")
        c.parse_error("python_projects", "web/pyproject.toml", "invalid TOML")
        self.assertEqual(len(c.warnings()), 2)

    def test_different_messages_kept(self):
        c = DiagnosticsCollector()
        c.parse_error("python_projects", "api/pyproject.toml", "invalid TOML: extra comma")
        c.parse_error("python_projects", "api/pyproject.toml", "invalid TOML: missing bracket")
        self.assertEqual(len(c.warnings()), 2)


class TestDiagnosticKinds(unittest.TestCase):
    """Each diagnostic kind is recorded correctly."""

    def test_parse_error_marks_degraded(self):
        c = DiagnosticsCollector()
        self.assertFalse(c.degraded)
        c.parse_error("python_projects", "pyproject.toml", "invalid TOML")
        self.assertTrue(c.degraded)

    def test_file_skipped_not_degraded(self):
        c = DiagnosticsCollector()
        c.file_skipped("repo_index", "path/to/file", "permission denied")
        self.assertFalse(c.degraded)

    def test_render_warning_not_degraded(self):
        c = DiagnosticsCollector()
        c.render_warning("render_c4", "SVG rendering failed")
        self.assertFalse(c.degraded)

    def test_model_warning_not_degraded(self):
        c = DiagnosticsCollector()
        c.model_warning("render_c4", "db-postgresql was found in code but not in model")
        self.assertFalse(c.degraded)

    def test_skipped_files_returns_only_skipped_kind(self):
        c = DiagnosticsCollector()
        c.parse_error("python_projects", "api/pyproject.toml", "invalid TOML")
        c.file_skipped("repo_index", "path/to/file", "permission denied")
        skipped = c.skipped_files()
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["path"], "path/to/file")
        self.assertEqual(skipped[0]["reason"], "permission denied")


class TestModelStatus(unittest.TestCase):
    """model_status() returns correct status string."""

    def test_no_diagnostics_is_ok(self):
        c = DiagnosticsCollector()
        self.assertEqual(c.model_status(), "ok")

    def test_drift_message_returns_drift(self):
        c = DiagnosticsCollector()
        c.model_warning("render_c4", "db-postgresql was found in the code but is not in the model")
        self.assertEqual(c.model_status(), "drift")

    def test_unknown_id_returns_invalid(self):
        c = DiagnosticsCollector()
        c.model_warning("render_c4", "unknown relationship id: ext-nonexistent")
        self.assertEqual(c.model_status(), "invalid")

    def test_not_found_returns_invalid(self):
        c = DiagnosticsCollector()
        c.model_warning("render_c4", "element 'missing-id' not found")
        self.assertEqual(c.model_status(), "invalid")

    def test_mixed_drift_and_invalid_returns_invalid(self):
        c = DiagnosticsCollector()
        c.model_warning("render_c4", "db-postgresql was found in the code but is not in the model")
        c.model_warning("render_c4", "unknown id in relationship")
        # invalid takes precedence
        self.assertEqual(c.model_status(), "invalid")


class TestModelErrors(unittest.TestCase):
    """model_errors() returns error messages only for invalid status."""

    def test_invalid_returns_messages(self):
        c = DiagnosticsCollector()
        c.model_warning("render_c4", "unknown id: ext-fake")
        self.assertEqual(c.model_errors(), ["unknown id: ext-fake"])

    def test_drift_returns_empty(self):
        c = DiagnosticsCollector()
        c.model_warning("render_c4", "db-postgresql was found in the code but is not in the model")
        self.assertEqual(c.model_errors(), [])

    def test_ok_returns_empty(self):
        c = DiagnosticsCollector()
        self.assertEqual(c.model_errors(), [])


class TestDrift(unittest.TestCase):
    """drift() returns model-tier diagnostics for drift status."""

    def test_drift_returns_entries(self):
        c = DiagnosticsCollector()
        c.model_warning("render_c4", "db-postgresql was found in the code but is not in the model")
        drift = c.drift()
        self.assertEqual(len(drift), 1)
        self.assertEqual(drift[0]["kind"], "model")

    def test_invalid_returns_empty_drift(self):
        c = DiagnosticsCollector()
        c.model_warning("render_c4", "unknown id: ext-fake")
        self.assertEqual(c.drift(), [])


class TestSummaryDict(unittest.TestCase):
    """summary_dict() returns the correct c4 diagnostics section."""

    def test_ok_returns_model_status_ok(self):
        c = DiagnosticsCollector()
        d = c.summary_dict()
        self.assertEqual(d["model_status"], "ok")
        self.assertNotIn("model_errors", d)
        self.assertNotIn("drift", d)

    def test_invalid_includes_model_errors(self):
        c = DiagnosticsCollector()
        c.model_warning("render_c4", "unknown id: ext-fake")
        d = c.summary_dict()
        self.assertEqual(d["model_status"], "invalid")
        self.assertEqual(d["model_errors"], ["unknown id: ext-fake"])
        self.assertNotIn("drift", d)

    def test_drift_includes_drift_entries(self):
        c = DiagnosticsCollector()
        c.model_warning("render_c4", "db-postgresql was found in the code but is not in the model")
        d = c.summary_dict()
        self.assertEqual(d["model_status"], "drift")
        self.assertIn("drift", d)
        self.assertNotIn("model_errors", d)


class TestRepoIndexCompatibility(unittest.TestCase):
    """RepoIndex calls skipped(path, reason) and warn(...) directly."""

    def test_skipped_two_arg_form_works(self):
        c = DiagnosticsCollector()
        c.skipped("/some/path", "permission denied")
        self.assertTrue(c.degraded is False)
        self.assertEqual(len(c.warnings()), 1)
        self.assertEqual(c.warnings()[0]["kind"], "skipped")

    def test_warn_parse_works(self):
        c = DiagnosticsCollector()
        c.warn("parse", file="api/pyproject.toml", detail="invalid TOML")
        self.assertTrue(c.degraded)
        self.assertEqual(len(c.warnings()), 1)
        self.assertEqual(c.warnings()[0]["kind"], "parse")


if __name__ == "__main__":
    unittest.main()
