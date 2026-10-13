"""
Python repositories the packaging metadata does not describe.

Two cases, both of which used to report zero projects and an empty dependency
graph: service folders carrying only a requirements.txt, and a repository with
no Python manifest at all, where the source roots have to be inferred from the
layout. Inferred roots are marked as such, and a noise guard keeps a release
script in a Go repository from being reported as a Python project.
"""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from helpers import run_analyzer, write

SERVICES = {
    "api/requirements.txt": "fastapi==0.110\nuvicorn\n",
    "api/main.py": "from fastapi import FastAPI\nfrom shared import models\napp = FastAPI()\n",
    "worker/requirements.txt": "celery[redis]==5.3\n",
    "worker/tasks.py": "from celery import Celery\nimport shared.models\napp = Celery('tasks')\n",
    "shared/__init__.py": "",
    "shared/models.py": "VALUE = 1\n",
}

NO_MANIFEST = {
    "svc/__init__.py": "",
    "svc/app.py": "from flask import Flask\nfrom svc import store\napp = Flask(__name__)\n",
    "svc/store.py": "import sqlite3\n",
    "ingest/__init__.py": "",
    "ingest/run.py": "from svc import store\n",
    "ingest/parse.py": "import csv\n",
}


def analyze(files, name="shop"):
    """Run the analyzer over ``files``; return (facts, summary, report, scan, graph)."""
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        repo = Path(tmp) / name
        out = Path(tmp) / "out"
        write(repo, files)
        facts, summary = run_analyzer(repo, out)
        report = (out / "ArchitectureReport.md").read_text(encoding="utf-8")
        scan = json.loads((out / "repository-scan.json").read_text(encoding="utf-8"))
        from scripts.build_graph import build_dependency_graph

        graph = build_dependency_graph(repo, include_orphans=True)
    return facts, summary, report, scan, graph


class RequirementsOnlyServicesAreProjectsTest(unittest.TestCase):
    """B-23: they were containers already, but not projects and not in the graph."""

    def setUp(self):
        self.facts, self.summary, self.report, self.scan, self.graph = analyze(SERVICES)

    def test_each_service_is_a_project(self):
        names = sorted(p["name"] for p in self.scan["projects"])
        self.assertEqual(names, ["api", "shared", "worker"])
        self.assertEqual(self.summary["projects_found"], 3)

    def test_imports_between_them_are_edges(self):
        self.assertEqual(self.graph, {"api": ["shared"], "shared": [], "worker": ["shared"]})

    def test_a_declared_service_is_not_marked_inferred(self):
        # api and worker have a requirements.txt; the shared package has
        # nothing declaring it, so it is honestly a guess from the layout.
        marks = {p["name"]: p["inferred"] for p in self.scan["projects"]}
        self.assertEqual(marks, {"api": False, "worker": False, "shared": True})
        self.assertEqual(self.summary["inferred_projects"], ["shared"])

    def test_the_containers_still_match_the_services(self):
        self.assertEqual(
            sorted(c["name"] for c in self.facts["containers"]), ["api", "worker"]
        )


class InferredSourceRootsTest(unittest.TestCase):
    """B-23: no pyproject.toml, no setup.py, no requirements.txt anywhere."""

    def setUp(self):
        self.facts, self.summary, self.report, self.scan, self.graph = analyze(NO_MANIFEST)

    def test_the_source_roots_become_projects(self):
        self.assertEqual(
            sorted(p["name"] for p in self.scan["projects"]), ["ingest", "svc"]
        )

    def test_they_are_marked_inferred(self):
        self.assertTrue(all(p["inferred"] for p in self.scan["projects"]))
        self.assertEqual(self.summary["inferred_projects"], ["ingest", "svc"])

    def test_imports_between_them_are_edges(self):
        self.assertEqual(self.graph, {"ingest": ["svc"], "svc": []})

    def test_the_stack_says_python(self):
        self.assertEqual(self.summary["technology_stack"], ["Python"])

    def test_the_report_says_the_projects_were_inferred(self):
        self.assertIn("Inferred projects:", self.report)
        self.assertIn("ingest, svc", self.report)
        self.assertIn("no manifest declares them", self.report)

    def test_a_framework_in_an_inferred_root_still_makes_a_container(self):
        self.assertEqual(
            [(c["name"], c["path"], c["technology"]) for c in self.facts["containers"]],
            [("svc", "svc", "Python, Flask")],
        )

    def test_the_run_is_not_degraded(self):
        self.assertEqual(self.summary["status"], "ok")


class NoiseGuardTest(unittest.TestCase):
    """A stray .py file does not make a repository a Python one."""

    def assert_no_python(self, files, name="svc"):
        _, summary, _, scan, _ = analyze(files, name=name)
        self.assertEqual([p for p in scan["projects"] if p["ecosystem"] == "Python"], [])
        self.assertNotIn("Python", summary["technology_stack"])

    def test_a_release_script_in_a_go_repository(self):
        self.assert_no_python({
            "go.mod": "module example.com/svc\n\ngo 1.22\n",
            "cmd/svc/main.go": "package main\n\nfunc main() {}\n",
            "scripts/release.py": "import subprocess\nsubprocess.run(['git', 'tag'])\n",
            "hack/gen.py": "print('generated')\n",
        })

    def test_a_sphinx_conf_in_a_docs_folder(self):
        self.assert_no_python({
            "go.mod": "module example.com/svc\n\ngo 1.22\n",
            "cmd/svc/main.go": "package main\n\nfunc main() {}\n",
            "docs/conf.py": "project = 'svc'\nextensions = []\n",
        })

    def test_a_single_loose_script_at_the_repository_root(self):
        self.assert_no_python({
            "go.mod": "module example.com/svc\n\ngo 1.22\n",
            "cmd/svc/main.go": "package main\n\nfunc main() {}\n",
            "setup_env.py": "import os\nos.environ['X'] = '1'\n",
        })

    def test_test_code_is_not_a_source_root(self):
        _, _, _, scan, _ = analyze({
            "svc/__init__.py": "",
            "svc/app.py": "from flask import Flask\napp = Flask(__name__)\n",
            "tests/test_app.py": "import svc.app\n",
            "tests/conftest.py": "import pytest\n",
        })
        self.assertEqual(sorted(p["name"] for p in scan["projects"]), ["svc"])

    def test_two_scripts_at_the_root_are_a_flat_layout(self):
        # No guard should hide a flat-layout program: two or more modules
        # side by side at the root is a source root, not a stray script.
        _, summary, _, scan, _ = analyze({
            "app.py": "from flask import Flask\nimport store\napp = Flask(__name__)\n",
            "store.py": "import sqlite3\n",
        })
        self.assertEqual(summary["technology_stack"], ["Python"])
        self.assertEqual(sorted(p["name"] for p in scan["projects"]), ["app", "store"])


class ManifestStillWinsTest(unittest.TestCase):
    """Inference only runs where the packaging metadata says nothing."""

    def test_a_packaged_repository_is_unchanged(self):
        _, summary, _, scan, _ = analyze({
            "pyproject.toml": '[project]\nname = "shop"\nversion = "1"\n',
            "shop/__init__.py": "",
            "shop/api.py": "from shop import store\n",
            "shop/store.py": "import sqlite3\n",
        })
        self.assertEqual(summary["inferred_projects"], [])
        self.assertTrue(all(not p["inferred"] for p in scan["projects"]))


if __name__ == "__main__":
    unittest.main()
