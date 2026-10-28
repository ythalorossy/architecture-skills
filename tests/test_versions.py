"""Every manifest, the skill metadata and the report stamp carry one version."""
import json
import re
import unittest

from helpers import REPO_ROOT

from scripts import generate_docs


def _json_version(relative, *path):
    data = json.loads((REPO_ROOT / relative).read_text(encoding="utf-8"))
    for key in path:
        data = data[key]
    return data["version"]


def _python_constant(relative, name):
    # Read, not imported: the review skill's scripts package shares the name `scripts`
    # with the c4 skill's, which this suite already has on sys.path.
    text = (REPO_ROOT / relative).read_text(encoding="utf-8")
    return re.search(rf'^{name} = "([^"]+)"', text, re.M).group(1)


class VersionTest(unittest.TestCase):
    def test_one_version_everywhere(self):
        skill = (REPO_ROOT / "skills" / "c4-diagrams" / "SKILL.md").read_text(encoding="utf-8")
        review_skill = (REPO_ROOT / "skills" / "architecture-review" / "SKILL.md").read_text(encoding="utf-8")
        versions = {
            "SKILL.md": re.search(r'^\s+version:\s*"([^"]+)"', skill, re.M).group(1),
            "architecture-review.SKILL.md": re.search(r'^\s+version:\s*"([^"]+)"', review_skill, re.M).group(1),
            "generate_docs.GENERATOR_VERSION": generate_docs.GENERATOR_VERSION,
            "collect_evidence.VERSION": _python_constant(
                "skills/architecture-review/scripts/collect_evidence.py", "VERSION"),
            "package.json": _json_version("package.json"),
            "plugin.json": _json_version("plugin.json"),
            "gemini-extension.json": _json_version("gemini-extension.json"),
            ".claude-plugin/plugin.json": _json_version(".claude-plugin/plugin.json"),
            ".claude-plugin/marketplace.json": _json_version(".claude-plugin/marketplace.json", "plugins", 0),
            ".cursor-plugin/plugin.json": _json_version(".cursor-plugin/plugin.json"),
            ".codex-plugin/plugin.json": _json_version(".codex-plugin/plugin.json"),
        }
        self.assertEqual(len(set(versions.values())), 1, versions)


if __name__ == "__main__":
    unittest.main()
