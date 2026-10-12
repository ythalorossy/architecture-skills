"""Tests for the diagnostics collector."""
import unittest

import sys
from pathlib import Path

# Ensure the skill scripts are on the path
REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "c4-diagrams"
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from scripts.diagnostics import DiagnosticsCollector


class TestRepoRelativePaths(unittest.TestCase):
    """summary.json describes files the way the user names them: relative to the repository."""

    def test_an_absolute_path_inside_the_repository_is_relativised(self):
        c = DiagnosticsCollector(root="/repo")
        c.file_skipped("repo_index", "/repo/api/huge.py", "too_large")
        self.assertEqual(c.skipped_files(), [{"path": "api/huge.py", "reason": "too_large"}])

    def test_a_path_outside_the_repository_is_kept_as_it_is(self):
        c = DiagnosticsCollector(root="/repo")
        c.render_warning("svg_render", "syntax-error", "c4-container.mmd")
        self.assertEqual(c.warnings()[0]["path"], "c4-container.mmd")

    def test_without_a_root_the_path_is_untouched(self):
        c = DiagnosticsCollector()
        c.file_skipped("repo_index", "/repo/api/huge.py", "too_large")
        self.assertEqual(c.skipped_files()[0]["path"], "/repo/api/huge.py")


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

    def test_file_skipped_marks_degraded(self):
        # skipped paths make the run degraded, exit 0
        c = DiagnosticsCollector()
        c.file_skipped("repo_index", "path/to/file", "permission denied")
        self.assertTrue(c.degraded)

    def test_render_warning_marks_degraded(self):
        # A diagram that failed to render is listed in warnings and degrades the run.
        c = DiagnosticsCollector()
        c.render_warning("svg_render", "c4-container: syntax-error — Parse error on line 9")
        self.assertTrue(c.degraded)
        self.assertEqual(c.warnings()[0]["kind"], "render")

    def test_invalid_model_marks_degraded(self):
        c = DiagnosticsCollector()
        c.model_error("render_c4", "relationships[0]: unknown from id 'ghost'")
        self.assertTrue(c.degraded)

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


class TestRepoIndexCompatibility(unittest.TestCase):
    """RepoIndex calls skipped(path, reason) and warn(...) directly."""

    def test_skipped_two_arg_form_works(self):
        # skipped paths make the run degraded, exit 0
        c = DiagnosticsCollector()
        c.skipped("/some/path", "permission denied")
        self.assertTrue(c.degraded)
        self.assertEqual(len(c.warnings()), 1)
        self.assertEqual(c.warnings()[0]["kind"], "skipped")

    def test_warn_parse_works(self):
        c = DiagnosticsCollector()
        c.warn("parse", file="api/pyproject.toml", detail="invalid TOML")
        self.assertTrue(c.degraded)
        self.assertEqual(len(c.warnings()), 1)
        self.assertEqual(c.warnings()[0]["kind"], "parse")


class TestModelWarningsDoNotDegrade(unittest.TestCase):
    def test_level4_skip_is_a_warning_not_an_invalid_model(self):
        # The collector used to guess the model tier from words like "not
        # found", so this note made summary.json say the model was invalid.
        c = DiagnosticsCollector()
        c.model_warning("code_diagrams", "repository not found at ../../repo; re-run analyze_repository.py "
                                         "or pass --repo <path> to render_c4.py")
        self.assertFalse(c.degraded)
        self.assertEqual(c.warnings()[0]["kind"], "model")


if __name__ == "__main__":
    unittest.main()
