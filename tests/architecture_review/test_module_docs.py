"""Every module of the architecture-review skill says what it is for."""
import ast
import unittest

import review_helpers as H

MODULES = sorted(p for p in (H.SKILL / "scripts").rglob("*.py")
                 if p.name != "__init__.py" and "__pycache__" not in p.parts)


class ModuleDocstringTest(unittest.TestCase):
    def test_there_are_modules_to_check(self):
        self.assertEqual([m.name for m in MODULES], ["check_review.py", "cli_support.py", "collect_evidence.py", "repo_scan.py", "signals.py"])

    def test_every_module_has_a_real_docstring(self):
        thin = {}
        for path in MODULES:
            text = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
            if len(text.split()) < 5:
                thin[path.name] = text
        self.assertEqual(thin, {}, f"missing or placeholder docstrings: {thin}")

    def test_the_package_marker_exists(self):
        self.assertTrue((H.SKILL / "scripts" / "__init__.py").exists())


if __name__ == "__main__":
    unittest.main()
