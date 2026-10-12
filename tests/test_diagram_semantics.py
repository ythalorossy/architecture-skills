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


class LayoutHeaderTest(unittest.TestCase):
    """No flowchart asks for a layout engine the renderer does not have.

    mermaid-cli 12.0.0 ships no ELK bundle: rendering with and without a
    `config: layout: elk` front-matter header produced byte-identical SVGs
    for every golden diagram. The header only misled readers about which
    engine lays the diagram out, so it is gone.
    """

    def _every_flowchart(self):
        model = render_c4.facts_only_model({
            "repository": "demo",
            "containers": [{"id": "api", "name": "API", "kind": "service", "technology": "Go",
                            "evidence": [], "used_by": []}],
            "data_stores": [{"id": "db", "name": "PostgreSQL", "technology": "PostgreSQL",
                             "evidence": [], "used_by": ["api"]}],
            "external_systems": [], "relationships": [],
        })
        model["system"]["name"] = "Demo"
        facts = {
            "containers": [{"id": "api", "name": "API", "compose_services": ["api"]}],
            "data_stores": [], "external_systems": [],
            "deployment": {"compose": [{"name": "api", "image": "demo:1", "ports": ["80:80"]}]},
        }
        return {
            "context": render_c4.context_diagram(model),
            "container": render_c4.container_diagram(model),
            "deployment": render_c4.deployment_diagram(facts, model),
            "component": render_c4._graph_diagram(
                model, {"data_stores": [], "external_systems": []}, {"id": "api"}, {"id": "api"},
                "API", {"a": {"group": ""}, "b": {"group": ""}}, {"a": ["b"]}, {}, "used_by_components"),
        }

    def test_no_diagram_carries_a_layout_header(self):
        for name, mermaid in self._every_flowchart().items():
            with self.subTest(diagram=name):
                self.assertTrue(mermaid.startswith("flowchart TB"), mermaid[:80])
                self.assertNotIn("layout:", mermaid)
                self.assertNotIn("elk", mermaid)


class RowStackingTest(unittest.TestCase):
    """Invisible `~~~` links still stack wide rows under the real engine.

    Without them mermaid-cli 12.0.0 draws 14 unconnected components in one
    2842px-wide row; with them the same diagram is 1226px wide and three
    rows deep. The trick stays, whatever the comment above it used to claim.
    """

    def test_wide_component_row_is_stacked(self):
        count = 2 * render_c4.ROW_WIDTH + 2
        nodes = {f"c{i:02}": {"group": ""} for i in range(count)}
        model = render_c4.facts_only_model({"repository": "r", "containers": [], "data_stores": [],
                                            "external_systems": [], "relationships": []})
        mermaid = render_c4._graph_diagram(
            model, {"data_stores": [], "external_systems": []}, {"id": "c"}, {"id": "c"},
            "API", nodes, {}, {}, "used_by_components")
        stacking = [line.strip() for line in mermaid.splitlines() if "~~~" in line]
        self.assertEqual(
            stacking,
            [f"c{i:02} ~~~ c{i + render_c4.ROW_WIDTH:02}"
             for i in range(count - render_c4.ROW_WIDTH)],
            mermaid,
        )


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
