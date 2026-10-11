"""Per-ecosystem detector baselines.

Each test reads `build_dependency_graph(fixture)` and asserts the project
names AND the dependency edges it observes. These are *characterisation*
tests: they pin the current behaviour of the detectors so that any change
to a detector's output shows up here. Multi-module structure must
be asserted, not just membership, so each fixture has at least one
producer and one consumer, and the consumer's edge list is checked.
"""
import unittest
from pathlib import Path

from helpers import SKILL  # noqa: F401  -- sets up sys.path so `scripts` is importable
from scripts.build_graph import build_dependency_graph

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "repos"


def _graph(name):
    return build_dependency_graph(FIXTURES / name)


class DetectorTest(unittest.TestCase):
    def test_dotnet_solution_projects_and_refs(self):
        graph = _graph("dotnet_sln")

        # Both projects come out of the .sln.
        self.assertEqual(set(graph), {"Core", "Web"})
        # Web has a <ProjectReference> to Core; Core is leaf.
        self.assertEqual(graph["Core"], [])
        self.assertEqual(graph["Web"], ["Core"])

    def test_maven_modules_and_deps(self):
        graph = _graph("maven_multi")

        # The aggregator pom is packaging=pom so it is not drawn; only the two
        # modules are. artifactIds are the names.
        self.assertEqual(set(graph), {"acme-core", "acme-web"})
        self.assertEqual(graph["acme-core"], [])
        self.assertEqual(graph["acme-web"], ["acme-core"])

    def test_gradle_includes(self):
        graph = _graph("gradle_kts")

        # settings.gradle.kts include(":core") and include(":web") become two
        # nodes (no src/ in the root, so the root is not drawn). Names drop
        # the leading colon.
        self.assertEqual(set(graph), {"core", "web"})
        self.assertEqual(graph["core"], [])
        self.assertEqual(graph["web"], ["core"])

    def test_go_packages(self):
        graph = _graph("go_mod")

        # One go.mod, so nodes are package groups: cmd/api and internal/store.
        self.assertEqual(set(graph), {"cmd/api", "internal/store"})
        # cmd/api imports internal/store; the store has no further imports.
        self.assertEqual(graph["cmd/api"], ["internal/store"])
        self.assertEqual(graph["internal/store"], [])

    def test_node_workspace_globs(self):
        graph = _graph("node_workspace")

        # The root package.json declares workspaces: ["packages/*"] and is
        # therefore not drawn; only the two members are.
        self.assertEqual(set(graph), {"@acme/core", "@acme/web"})
        # The workspace dependency resolves by name.
        self.assertEqual(graph["@acme/core"], [])
        self.assertEqual(graph["@acme/web"], ["@acme/core"])

    def test_python_distribution_requirements(self):
        graph = _graph("python_dist")

        # Two distributions, each a pyproject.toml. Names come from
        # [project].name; edges from declared requirements naming another
        # distribution, normalised per PEP 503.
        self.assertEqual(set(graph), {"acme-core", "acme-web"})
        self.assertEqual(graph["acme-core"], [])
        self.assertEqual(graph["acme-web"], ["acme-core"])


if __name__ == "__main__":
    unittest.main()