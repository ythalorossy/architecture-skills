"""
What the C4 diagrams say, not just whether they parse.
"""
import unittest

from helpers import write  # noqa: F401  (puts the skill on sys.path)

from scripts import render_c4


class MergeRelationshipsTest(unittest.TestCase):
    """One edge per pair: the most specific description wins, technologies add up."""

    def test_code_evidence_beats_compose_depends_on(self):
        merged = render_c4._merge_relationships([
            {"from": "api", "to": "db", "description": "Depends on", "technology": ""},
            {"from": "api", "to": "db", "description": "Reads/writes", "technology": "psycopg"},
        ])
        self.assertEqual(merged, [{"from": "api", "to": "db", "description": "Reads/writes", "technology": "psycopg"}])

    def test_first_specific_description_is_kept_and_technologies_combined(self):
        merged = render_c4._merge_relationships([
            {"from": "web", "to": "api", "description": "Calls /api", "technology": "HTTP"},
            {"from": "web", "to": "api", "description": "Fetches books", "technology": "JSON"},
            {"from": "web", "to": "api", "description": "Depends on", "technology": "HTTP"},
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["description"], "Calls /api")
        self.assertEqual(merged[0]["technology"], "HTTP, JSON")

    def test_self_edges_are_dropped_and_pairs_keep_their_order(self):
        merged = render_c4._merge_relationships([
            {"from": "a", "to": "a", "description": "Calls"},
            {"from": "b", "to": "c", "description": "Calls"},
            {"from": "a", "to": "b", "description": "Calls"},
        ])
        self.assertEqual([(r["from"], r["to"]) for r in merged], [("b", "c"), ("a", "b")])


def _graph(groups, edges):
    """Component graph {nodes, edges} from {group: [node, ...]} and [(a, b), ...]."""
    nodes = {n: {"group": g} for g, members in groups.items() for n in members}
    out = {}
    for a, b in edges:
        out.setdefault(a, []).append(b)
    return {"nodes": nodes, "edges": out}


class SharedComponentTest(unittest.TestCase):
    def test_hub_is_found_even_when_reduction_hides_its_edges(self):
        # A chain n0 -> n1 -> ... -> n23 where every node also uses util. The
        # graph is dense, so reduction keeps only n23 -> util; util is still
        # used by all 24 others and belongs in the Shared box.
        chain = [f"n{i:02}" for i in range(24)]
        edges = list(zip(chain, chain[1:])) + [(n, "util") for n in chain]
        [(_, _, nodes, drawn, notes)] = render_c4._component_views(_graph({"": chain + ["util"]}, edges))
        self.assertTrue(nodes["util"]["shared"])
        self.assertIn("util (24)", " ".join(notes))
        self.assertFalse(any("util" in targets for targets in drawn.values()))


class SplitPartsTest(unittest.TestCase):
    def test_edge_to_another_part_keeps_the_target_as_a_stub(self):
        a = [f"a{i:02}" for i in range(13)]
        b = [f"b{i:02}" for i in range(12)]
        graph = _graph({"alpha": a, "beta": b}, [("a00", "b00"), ("a01", "a02")])
        views = render_c4._component_views(graph, overview=False)
        part_a = next(v for v in views if "a00" in v[2] and not v[2]["a00"].get("stub"))
        _, _, nodes, edges, _ = part_a
        self.assertIn("b00", edges["a00"])
        self.assertIn("part", nodes["b00"]["stub"])
        self.assertNotIn("stub", nodes["a01"])

    def test_stub_is_drawn_outside_the_boundary_with_a_dashed_edge(self):
        a = [f"a{i:02}" for i in range(13)]
        b = [f"b{i:02}" for i in range(12)]
        graph = _graph({"alpha": a, "beta": b}, [("a00", "b00")])
        views = render_c4._component_views(graph, overview=False)
        _, title, nodes, edges, _ = next(v for v in views if "a00" in v[2] and not v[2]["a00"].get("stub"))
        model = render_c4.facts_only_model({"repository": "r", "containers": [], "data_stores": [],
                                            "external_systems": [], "relationships": []})
        facts = {"data_stores": [], "external_systems": []}
        mermaid = render_c4._graph_diagram(model, facts, {"id": "c"}, {"id": "c"}, title, nodes, edges, {}, "used_by_components")
        boundary_end = mermaid.index("\n    end\n")
        self.assertGreater(mermaid.index("b00["), boundary_end, "stub must be outside the container boundary")
        self.assertIn("a00 -.-> b00", mermaid)


class ComposeTest(unittest.TestCase):
    """docker-compose.yml is read the same way everywhere, comments included."""

    COMPOSE = (
        "services:\n"
        "  db:   # main database\n"
        "    image: azure-sql-edge:latest   # SQL Server for ARM\n"
        "  app:  # backend\n"
        "    build: ./app\n"
        "    depends_on:\n"
        "      - db   # wait for it\n"
    )

    def facts_and_container_diagram(self):
        import tempfile
        from pathlib import Path
        from helpers import run_analyzer

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            write(repo, {"docker-compose.yml": self.COMPOSE, "app/main.py": "print('hi')\n"})
            facts, _ = run_analyzer(repo, Path(tmp) / "out")
            mermaid = (Path(tmp) / "out" / "c4-container.mmd").read_text(encoding="utf-8")
        return facts, mermaid

    def test_comments_do_not_leak_into_names_or_drop_edges(self):
        facts, mermaid = self.facts_and_container_diagram()
        services = [s["name"] for s in facts["deployment"]["compose"]]
        self.assertEqual(services, ["db", "app"])
        self.assertEqual([s["image"] for s in facts["deployment"]["compose"]][0], "azure-sql-edge:latest")
        self.assertEqual([(r["from"], r["to"]) for r in facts["relationships"]], [("app", "db-sql-server")])
        self.assertIn("app -->", mermaid)

    def test_compose_store_is_drawn_as_a_database_in_every_view(self):
        facts, mermaid = self.facts_and_container_diagram()
        self.assertEqual([s["name"] for s in facts["data_stores"]], ["SQL Server"])
        self.assertIn('db_sql_server[("', mermaid)
        model = render_c4.facts_only_model(facts)
        deployment = render_c4.deployment_diagram(facts, model)
        self.assertRegex(deployment, r'svc_db\[\("`\*\*db\*\*')


class FactsOnlyContainerDiagramTest(unittest.TestCase):
    def test_bookshop_edges_use_the_code_evidence(self):
        from helpers import run_analyzer
        import tempfile
        from pathlib import Path

        fixture = Path(__file__).resolve().parent / "fixtures" / "repos" / "bookshop"
        with tempfile.TemporaryDirectory() as tmp:
            run_analyzer(fixture, tmp)
            mermaid = (Path(tmp) / "c4-container.mmd").read_text(encoding="utf-8")
        self.assertIn('bookshop_api -->|"`Reads/writes`"| db_postgresql', mermaid)
        self.assertIn("Calls /api", mermaid)
        self.assertNotIn("Depends on", mermaid)


if __name__ == "__main__":
    unittest.main()
