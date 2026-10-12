"""One rule per decision, applied the same way everywhere.

Go packages are grouped by the same folder list in the component view and
in the code-structure view, and a test folder is a test folder whatever
case it is written in.
"""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from helpers import run_analyzer, write

from scripts import c4_facts, code_facts


class GoGroupingTest(unittest.TestCase):
    """`services/` expands in both views or in neither."""

    def test_a_services_package_keeps_its_second_segment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, {
                "go.mod": "module example.com/shop\n\ngo 1.22\n",
                "services/billing/handler.go": "package billing\n\nfunc Handle() {}\n",
                "services/catalog/handler.go": "package catalog\n\nfunc Handle() {}\n",
            })

            graph = code_facts.code_components({"shop": root})

        self.assertEqual(
            sorted(node["label"] for node in graph["nodes"].values()),
            ["services/billing", "services/catalog"],
        )


class TestFolderCaseTest(unittest.TestCase):
    """A folder called Tests holds test code, exactly like tests."""

    def analyze(self, files):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            write(root, files)
            with contextlib.redirect_stdout(io.StringIO()):
                facts, _ = run_analyzer(root, Path(tmp) / "out")
        return facts

    FLASK_APP = "from flask import Flask\napp = Flask(__name__)\n"

    def test_a_framework_imported_only_by_the_tests_is_not_the_technology(self):
        facts = self.analyze({
            "requirements.txt": "requests\n",
            "app/main.py": "import requests\n",
            "Tests/test_api.py": self.FLASK_APP,
        })

        self.assertEqual([c["technology"] for c in facts["containers"] if "Flask" in c["technology"]], [])

    def test_the_same_file_outside_a_test_folder_still_is(self):
        """The control: only the folder name differs."""
        facts = self.analyze({
            "requirements.txt": "requests\n",
            "app/main.py": "import requests\n",
            "service/api.py": self.FLASK_APP,
        })

        self.assertEqual([c["technology"] for c in facts["containers"]], ["Python, Flask"])

    def test_an_import_in_a_capitalised_test_folder_is_not_a_data_store(self):
        facts = self.analyze({
            "requirements.txt": "fastapi\n",
            "app/main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
            "Tests/test_store.py": "import psycopg\nconn = psycopg.connect('postgresql://localhost/db')\n",
        })

        self.assertEqual([store["name"] for store in facts["data_stores"]], [])

    def test_a_main_in_a_capitalised_test_folder_is_not_an_entry_point(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, {
                "Tests/Main.java": "public class Main { public static void main(String[] a) {} }\n",
            })

            self.assertFalse(c4_facts._has_jvm_main(root, None))

    def test_a_url_in_a_capitalised_test_folder_is_not_an_external_system(self):
        facts = self.analyze({
            "requirements.txt": "fastapi\n",
            "app/main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
            "Tests/application.yml": "partner:\n  url: https://partner.example/v1\n",
        })

        self.assertEqual([system["name"] for system in facts["external_systems"]], [])

    def test_requirements_in_a_capitalised_test_folder_is_not_a_service(self):
        facts = self.analyze({
            "requirements.txt": "fastapi\n",
            "app/main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
            "Tests/requirements.txt": "pytest\n",
        })

        self.assertEqual(len(facts["containers"]), 1, facts["containers"])


class TestFileNameTest(unittest.TestCase):
    """A TypeScript test file is named, not foldered: api.test.ts is test code."""

    def test_a_dot_test_file_is_test_code(self):
        self.assertTrue(code_facts._is_test(Path("web/src/api.test.ts"), Path("web")))
        self.assertTrue(code_facts._is_test(Path("web/src/api.spec.tsx"), Path("web")))

    def test_a_source_file_is_not(self):
        self.assertFalse(code_facts._is_test(Path("web/src/api.ts"), Path("web")))
        self.assertFalse(code_facts._is_test(Path("web/src/latest.ts"), Path("web")))


class SharedPatternsTest(unittest.TestCase):
    """The patterns two modules used to carry a copy of each."""

    def test_the_go_module_line_is_read_by_one_pattern(self):
        from scripts import go_projects, paths
        self.assertIs(go_projects.MODULE, paths.GO_MODULE_LINE)

    def test_the_requirements_file_name_is_matched_by_one_pattern(self):
        from scripts import python_projects, paths
        self.assertTrue(paths.REQUIREMENTS_FILE.match("requirements-dev.txt"))
        self.assertIsNone(paths.REQUIREMENTS_FILE.match("my-requirements.txt"))
        self.assertIs(python_projects.REQUIREMENTS_FILE, paths.REQUIREMENTS_FILE)

    def test_the_generic_url_key_names_are_one_list(self):
        from scripts import paths
        self.assertIn("base_url", paths.GENERIC_URL_KEYS)
        self.assertIn("address", paths.GENERIC_URL_KEYS)
        self.assertIs(c4_facts.GENERIC_URL_KEYS, paths.GENERIC_URL_KEYS)


if __name__ == "__main__":
    unittest.main()
