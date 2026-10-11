"""
Regression tests for path handling: a sibling module's files must never leak
into another module's analysis, a bad path must be reported as a user error
rather than an internal one, and the skill's own commands must resolve from
any working directory.
"""
import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import SKILL, write

ANALYZER = SKILL / "scripts" / "analyze_repository.py"

SPRING_MAIN = (
    "package app;\n"
    "import org.springframework.boot.autoconfigure.SpringBootApplication;\n"
    "@SpringBootApplication\n"
    "public class Main { public static void main(String[] args) { } }\n"
)
POM_ROOT = (
    "<project><modelVersion>4.0.0</modelVersion><groupId>demo</groupId>"
    "<artifactId>demo</artifactId><version>1</version><packaging>pom</packaging>"
    "<modules><module>weather-api</module><module>weather-infra</module></modules></project>"
)


def _analyze(repo: Path, out: Path):
    from scripts.analyze_repository import RepositoryAnalyzer

    with contextlib.redirect_stdout(io.StringIO()):
        RepositoryAnalyzer(str(repo), str(out), no_svg=True).run()
    return json.loads((out / "c4-facts.json").read_text(encoding="utf-8"))


class RepoIndexUnderTest(unittest.TestCase):
    def test_walk_under_returns_only_files_inside_the_directory(self):
        from scripts.repo_index import RepoIndex

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            write(repo, {"a/x.py": "", "a/sub/y.py": "", "ab/z.py": "", "root.py": ""})
            index = RepoIndex.build(repo)
            names = sorted(p.relative_to(repo.resolve()).as_posix() for p in index.walk(lambda n: n.endswith(".py"), under=repo / "a"))
            self.assertEqual(names, ["a/sub/y.py", "a/x.py"])

    def test_walk_under_outside_the_repository_yields_nothing(self):
        from scripts.repo_index import RepoIndex

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            write(repo, {"a/x.py": ""})
            index = RepoIndex.build(repo)
            self.assertEqual(list(index.walk(lambda n: True, under=Path(tmp))), [])


class SiblingModulesTest(unittest.TestCase):
    """Each module is analysed alone; a sibling's main class or modules must not crash it."""

    def test_java_library_module_next_to_a_spring_app_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            write(repo, {
                "pom.xml": POM_ROOT,
                "weather-api/pom.xml": (
                    "<project><groupId>demo</groupId><artifactId>weather-api</artifactId><version>1</version>"
                    "<dependencies><dependency><groupId>org.springframework.boot</groupId>"
                    "<artifactId>spring-boot-starter-web</artifactId></dependency></dependencies>"
                    "<build><plugins><plugin><artifactId>spring-boot-maven-plugin</artifactId></plugin>"
                    "</plugins></build></project>"
                ),
                "weather-api/src/main/java/app/Main.java": SPRING_MAIN,
                "weather-infra/pom.xml": (
                    "<project><groupId>demo</groupId><artifactId>weather-infra</artifactId><version>1</version>"
                    "<dependencies><dependency><groupId>org.springframework.boot</groupId>"
                    "<artifactId>spring-boot-starter</artifactId></dependency></dependencies></project>"
                ),
                "weather-infra/src/main/java/infra/Cache.java": "package infra;\npublic class Cache { }\n",
            })
            facts = _analyze(repo, Path(tmp) / "out")

            names = {c["name"] for c in facts["containers"]}
            self.assertIn("weather-api", names)
            self.assertNotIn("weather-infra", names, "a library module is not a container")

    def test_python_packages_do_not_see_each_others_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            write(repo, {
                "api/pyproject.toml": '[project]\nname = "api-svc"\nversion = "0.1"\ndependencies = ["fastapi"]\n',
                "api/app/main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
                "worker/pyproject.toml": '[project]\nname = "worker-svc"\nversion = "0.1"\ndependencies = ["celery"]\n',
                "worker/tasks.py": "from celery import Celery\napp = Celery()\n",
            })
            facts = _analyze(repo, Path(tmp) / "out")

            names = {c["name"] for c in facts["containers"]}
            self.assertTrue({"api-svc", "worker-svc"} <= names, names)


class UserPathErrorsTest(unittest.TestCase):
    """A mistyped path is a user error: one line that names the path, no 'internal error'."""

    def _run(self, *args):
        return subprocess.run([sys.executable, str(ANALYZER), *args], capture_output=True, text=True, timeout=120)

    def test_missing_repository_is_a_user_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._run(str(Path(tmp) / "nope"), "--no-svg", "--output", str(Path(tmp) / "out"))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("repository folder not found", proc.stderr)
            self.assertNotIn("internal error", proc.stderr)
            self.assertNotIn("Traceback", proc.stderr)

    def test_a_file_given_as_repository_is_a_user_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "main.py"
            file.write_text("print(1)\n", encoding="utf-8")
            proc = self._run(str(file), "--no-svg", "--output", str(Path(tmp) / "out"))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("expected a repository folder", proc.stderr)
            self.assertNotIn("internal error", proc.stderr)

    def test_output_path_that_is_a_file_is_a_user_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            write(repo, {"a.py": ""})
            blocker = Path(tmp) / "blocker"
            blocker.write_text("x", encoding="utf-8")
            proc = self._run(str(repo), "--no-svg", "--output", str(blocker))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("existing file", proc.stderr)
            self.assertNotIn("internal error", proc.stderr)

    def test_output_inside_the_skill_folder_is_refused_and_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            write(repo, {"a.py": ""})
            target = SKILL / "should-not-exist"
            self.addCleanup(lambda: shutil.rmtree(target, ignore_errors=True))
            proc = self._run(str(repo), "--no-svg", "--output", str(target))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("inside the skill folder", proc.stderr)
            self.assertFalse(target.exists())


class SkillCommandsTest(unittest.TestCase):
    """SKILL.md must not tell the agent to run a path that only resolves from the skill folder."""

    def test_skill_commands_use_the_skill_placeholder(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        bare = re.findall(r"python3?\s+(?!\")(?:scripts|assets|references)/", text)
        self.assertEqual(bare, [], "a bare scripts/ path only works from the skill folder")

    def test_every_script_the_skill_names_exists(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        for name in re.findall(r'<skill>/(scripts/[\w.]+\.py)', text):
            self.assertTrue((SKILL / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
