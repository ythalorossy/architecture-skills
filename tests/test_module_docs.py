"""Every script module says what it is for.

The skill is 25 modules that call each other through plain functions, with no
framework or type annotations to read structure off. A module with no
docstring is one a contributor has to infer from its imports, and twelve of
them had none. This is a ratchet: a new module arrives with a sentence saying
what it does, or this fails.

Kept small on purpose. It checks that the docstring exists and is not a
placeholder; whether it is any good is a review question, not a test.
"""
import ast
import unittest

from helpers import SKILL

SCRIPTS = SKILL / "scripts"

# A package marker is a module in name only. Anything else is a real one.
EXEMPT = {"__init__.py"}


def _modules():
    return sorted(p for p in SCRIPTS.glob("*.py") if p.name not in EXEMPT)


class ModuleDocstringTest(unittest.TestCase):
    def test_every_module_has_one(self):
        missing = [
            path.name for path in _modules()
            if not ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
        ]

        self.assertEqual(missing, [], f"modules with no docstring: {missing}")

    def test_none_of_them_is_a_placeholder(self):
        # A one-word restatement of the filename is the shape this guards
        # against: "scan_repo." tells a reader nothing the path did not.
        thin = {}
        for path in _modules():
            text = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
            if len(text.split()) < 5:
                thin[path.name] = text
        self.assertEqual(thin, {}, f"docstrings too short to say anything: {thin}")

    def test_the_package_marker_is_still_the_only_exemption(self):
        # If scripts/ grows a second trivial module, decide deliberately
        # rather than discovering the exemption list has quietly widened.
        self.assertEqual(sorted(EXEMPT), ["__init__.py"])
        self.assertTrue((SCRIPTS / "__init__.py").exists())


if __name__ == "__main__":
    unittest.main()
