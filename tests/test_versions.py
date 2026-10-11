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


class VersionTest(unittest.TestCase):
    def test_one_version_everywhere(self):
        skill = (REPO_ROOT / "skills" / "c4-diagrams" / "SKILL.md").read_text(encoding="utf-8")
        versions = {
            "SKILL.md": re.search(r'^\s+version:\s*"([^"]+)"', skill, re.M).group(1),
            "generate_docs.GENERATOR_VERSION": generate_docs.GENERATOR_VERSION,
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
