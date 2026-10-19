"""Each skill is self-contained: its scripts never reach into another skill's folder.

Skills share no code: each folder carries everything it runs on, so it works
the same however the plugin is installed. They still exchange data
(architecture-review reads the c4-facts.json that c4-diagrams writes), which
is a file contract, not an import.
"""
import re
import unittest

from helpers import REPO_ROOT

SKILLS = REPO_ROOT / "skills"

# A path built from the skill folder's parent is how a script would find a
# sibling skill or a plugin-level folder; loading by file path is how it would import one.
SIBLING_REACH = re.compile(r"SKILL_DIR\.parent|spec_from_file_location|^\s*(?:from|import)\s+shared\b")


class SkillIsolationTest(unittest.TestCase):
    def test_no_skill_script_reaches_into_a_sibling_skill(self):
        offenders = []
        for script in sorted(SKILLS.glob("*/scripts/**/*.py")):
            for number, line in enumerate(script.read_text(encoding="utf-8").splitlines(), 1):
                if SIBLING_REACH.search(line):
                    offenders.append(f"{script.relative_to(REPO_ROOT)}:{number}: {line.strip()}")
        self.assertEqual(offenders, [])

    def test_the_review_suite_uses_nothing_from_the_shared_tests_folder(self):
        # tests/architecture_review/ is its own suite: its own helpers, fixtures and process.
        reach = re.compile(r"from helpers import|import helpers\b|tests/fixtures|\"fixtures\" / \"repos\" / \"(?!architecture)")
        offenders = []
        for path in sorted((REPO_ROOT / "tests" / "architecture_review").glob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if reach.search(line):
                    offenders.append(f"{path.name}:{number}: {line.strip()}")
        self.assertEqual(offenders, [])

    def test_there_is_no_plugin_level_code_folder(self):
        self.assertFalse((REPO_ROOT / "shared").exists(), "skills must not depend on a folder outside themselves")

    def test_every_skill_carries_its_own_cli_support(self):
        for skill in sorted(p for p in SKILLS.iterdir() if (p / "SKILL.md").is_file()):
            self.assertTrue((skill / "scripts" / "cli_support.py").is_file(), skill.name)


if __name__ == "__main__":
    unittest.main()
