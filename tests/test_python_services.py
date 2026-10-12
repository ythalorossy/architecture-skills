"""
Python services that have no pyproject.toml or setup.py, only a
requirements.txt: common for small FastAPI/Flask/Celery services.
"""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from helpers import run_analyzer, write

SERVICES = {
    "api/requirements.txt": "fastapi==0.110\nuvicorn\npsycopg[binary]\n",
    "api/main.py": "from fastapi import FastAPI\nimport psycopg\napp = FastAPI()\n",
    "worker/requirements.txt": "celery[redis]==5.3\n",
    "worker/tasks.py": "from celery import Celery\napp = Celery('tasks', broker='redis://cache:6379/0')\n",
    "worker/tests/test_tasks.py": "import pytest\n",
}
COMPOSE = (
    "services:\n"
    "  api:\n    build: ./api\n    depends_on:\n      - db\n"
    "  worker:\n    build: ./worker\n"
    "  db:\n    image: postgres:16\n"
)


class RequirementsOnlyServicesTest(unittest.TestCase):
    def analyze(self, files):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            repo = Path(tmp) / "shop"
            write(repo, files)
            facts, summary = run_analyzer(repo, Path(tmp) / "out")
        return facts, summary, out.getvalue()

    def test_each_service_folder_is_its_own_container(self):
        facts, _, _ = self.analyze(SERVICES)
        containers = sorted((c["name"], c["path"], c["technology"]) for c in facts["containers"])
        self.assertEqual(containers, [
            ("api", "api", "Python, FastAPI"),
            ("worker", "worker", "Python, Celery"),
        ])

    def test_compose_build_contexts_match_the_services(self):
        facts, _, _ = self.analyze({**SERVICES, "docker-compose.yml": COMPOSE})
        names = sorted(c["name"] for c in facts["containers"])
        self.assertEqual(names, ["api", "worker"], "no duplicate or phantom container")
        self.assertIn(("api", "db-postgresql"), {(r["from"], r["to"]) for r in facts["relationships"]})

    def test_root_requirements_with_code_at_the_root(self):
        facts, _, _ = self.analyze({
            "requirements.txt": "flask\n",
            "app.py": "from flask import Flask\napp = Flask(__name__)\n",
        })
        self.assertEqual([(c["name"], c["path"]) for c in facts["containers"]], [("shop", ".")])

    def test_root_service_does_not_swallow_nested_services(self):
        facts, _, _ = self.analyze({
            **SERVICES,
            # Shared tooling at the root, no framework: not a container, and
            # it must not absorb the services' FastAPI/Celery signals.
            "requirements.txt": "pyyaml\n",
            "scripts/seed.py": "import yaml\n",
        })
        self.assertEqual(sorted(c["name"] for c in facts["containers"]), ["api", "worker"])


class NothingDetectedTest(unittest.TestCase):
    def test_no_container_is_reported(self):
        # Libraries only: projects exist, nothing runs on its own.
        files = {
            "packages/core/pyproject.toml": '[project]\nname = "core"\nversion = "1"\n',
            "packages/core/core/__init__.py": "VALUE = 1\n",
        }
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            repo = Path(tmp) / "libs"
            write(repo, files)
            facts, summary = run_analyzer(repo, Path(tmp) / "out")
        # The repository becomes one placeholder container so its components
        # still have a home; that must be flagged, not reported as healthy.
        self.assertEqual([(c["name"], c["kind"]) for c in facts["containers"]], [("libs", "unknown")])
        detection = [w for w in summary["warnings"] if w["kind"] == "detection"]
        self.assertEqual(len(detection), 1, summary["warnings"])
        self.assertIn("no container", detection[0]["message"])
        self.assertIn("WARNING: no container", out.getvalue())
        # A library-only repository is understood, just not runnable: still ok.
        self.assertEqual(summary["status"], "ok")

    def test_nothing_recognized_is_degraded(self):
        # No manifest, no code: the analyzer found nothing to draw and must
        # say so instead of reporting a clean run with an empty diagram.
        files = {
            "README.md": "# Notes\n",
            "notes.txt": "plain text, no code here\n",
        }
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            repo = Path(tmp) / "nothing"
            write(repo, files)
            facts, summary = run_analyzer(repo, Path(tmp) / "out")
        self.assertEqual(facts["containers"], [])
        detection = [w for w in summary["warnings"] if w["kind"] == "detection"]
        self.assertEqual(len(detection), 1, summary["warnings"])
        self.assertIn("no container", detection[0]["message"])
        self.assertIn("WARNING: no container", out.getvalue())
        self.assertEqual(summary["status"], "degraded")


if __name__ == "__main__":
    unittest.main()
