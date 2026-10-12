"""
Tests for safe Mermaid rendering with adversarial identifiers.

tests/test_render_ids.py verifies:
- person named __system__ keeps both nodes
- container named __boundary__ is drawn
- adversarial corpus parses with mmdc (optional, skipped without mmdc)

The module under test is the existing render_c4 module, which will call mermaid_syntax
once implemented.
"""
import os
import re
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401  (puts the skill on sys.path)

# Module under test
from scripts import render_c4


def _make_minimal_model(**overrides):
    """A minimal valid model with the given overrides applied."""
    model = {
        "system": {"name": "TestSystem", "description": ""},
        "people": [],
        "containers": [],
        "external_systems": [],
        "relationships": [],
        "flows": [],
        "excluded": [],
    }
    for k, v in overrides.items():
        keys = k.split(".")
        target = model
        for key in keys[:-1]:
            target = target.setdefault(key, {})
        target[keys[-1]] = v
    return model


class PersonNamedSystemTest(unittest.TestCase):
    """A person with id __system__ must not collide with the internal __system__ node."""

    def test_person_named_system_keeps_both_nodes(self):
        model = _make_minimal_model(
            people=[{"id": "__system__", "name": "System User", "description": ""}],
            containers=[{"id": "svc", "name": "MyService", "technology": "Python"}],
            relationships=[{"from": "__system__", "to": "svc", "description": "Uses"}],
        )
        mermaid = render_c4.context_diagram(model)
        # The rendered diagram must contain two distinct node ids.
        # The internal system node and the person named __system__ must both appear.
        lines = mermaid.splitlines()
        node_ids = set()
        for line in lines:
            if "styleDef" not in line and ("[" in line or "(" in line):
                # Extract the id at the start of the node definition
                parts = line.strip().split()
                if parts:
                    node_ids.add(parts[0])
        self.assertGreaterEqual(len(node_ids), 2,
            f"Expected at least 2 distinct node ids, got {node_ids} in:\n{mermaid}")


class ContainerNamedBoundaryTest(unittest.TestCase):
    """A container with id __boundary__ must not collide with the internal boundary node."""

    def test_container_named_boundary_is_drawn(self):
        model = _make_minimal_model(
            containers=[
                {"id": "__boundary__", "name": "BoundaryService", "technology": "Python"},
            ],
            relationships=[],
        )
        mermaid = render_c4.container_diagram(model)
        # The __boundary__ container must appear as a distinct node.
        lines = mermaid.splitlines()
        node_ids = set()
        for line in lines:
            parts = line.strip().split()
            if parts and ("]" in line or ")" in line):
                node_ids.add(parts[0])
        self.assertGreaterEqual(len(node_ids), 2,
            f"Expected at least 2 distinct node ids, got {node_ids} in:\n{mermaid}")


class ComposeServiceEndTest(unittest.TestCase):
    """A compose service named 'end' must render without breaking the diagram."""

    def test_compose_service_named_end_parses(self):
        facts = {
            "deployment": {
                "compose": [
                    {"name": "end", "image": "nginx:latest"},
                ]
            },
            "containers": [],
        }
        model = _make_minimal_model(
            containers=[{"id": "svc", "name": "MyService"}],
        )
        mermaid = render_c4.deployment_diagram(facts, model)
        self.assertIsNotNone(mermaid, "deployment_diagram returned None")
        # The 'end' service must be present as a named node, not as the Mermaid 'end' keyword.
        self.assertIn("end", mermaid, f"'end' service not found in:\n{mermaid}")


class FlowDiagramKeywordTest(unittest.TestCase):
    """A person named 'box' must not break the flow sequence diagram."""

    def test_person_named_box_in_flow(self):
        model = _make_minimal_model(
            people=[{"id": "box", "name": "Box Person"}],
            containers=[{"id": "svc", "name": "MyService"}],
            relationships=[{"from": "box", "to": "svc", "description": "Uses"}],
            flows=[{
                "name": "Main flow",
                "steps": [
                    {"from": "box", "to": "svc", "description": "Request"},
                ]
            }],
        )
        facts = {"containers": []}
        flows = render_c4.flow_diagrams(model, facts)
        self.assertEqual(len(flows), 1)
        _, _, mermaid, _ = flows[0]
        # The 'box' participant must appear as a named participant, not as a Mermaid keyword.
        self.assertIn("box", mermaid, f"'box' participant not found in:\n{mermaid}")


class ExactIdsTest(unittest.TestCase):
    """Ids are readable, unique within a diagram, and never a reserved word."""

    def test_flow_participant_named_box_gets_a_safe_id(self):
        model = _make_minimal_model(
            people=[{"id": "box", "name": "Box Person"}],
            containers=[{"id": "svc", "name": "MyService"}],
            flows=[{"name": "Main", "steps": [{"from": "box", "to": "svc", "description": "Request"}]}],
        )
        _, _, mermaid, _ = render_c4.flow_diagrams(model, {"containers": []})[0]
        self.assertIn("actor box_2 as Box Person", mermaid)
        self.assertIn("box_2->>svc: Request", mermaid)

    def test_container_named_boundary_and_the_boundary_differ(self):
        model = _make_minimal_model(
            containers=[{"id": "boundary", "name": "Boundary service", "technology": "Python"}],
        )
        mermaid = render_c4.container_diagram(model)
        self.assertIn('subgraph boundary["', mermaid)
        self.assertIn('boundary_2["', mermaid)

    def test_ids_that_slug_alike_stay_distinct(self):
        model = _make_minimal_model(
            containers=[
                {"id": "orders-api", "name": "Orders API"},
                {"id": "orders_api", "name": "Orders API v2"},
            ],
            relationships=[{"from": "orders-api", "to": "orders_api", "description": "Calls"}],
        )
        mermaid = render_c4.container_diagram(model)
        self.assertIn('orders_api["', mermaid)
        self.assertIn('orders_api_2["', mermaid)
        self.assertIn("orders_api -->", mermaid)
        self.assertIn(" orders_api_2\n", mermaid)

    def test_backticks_in_text_cannot_end_the_label(self):
        model = _make_minimal_model(
            containers=[{"id": "api", "name": "API `v2`", "description": "Serves `GET /books`"}],
        )
        mermaid = render_c4.container_diagram(model)
        # Every backtick is a "`…`" delimiter: none inside label text.
        import re
        labels = re.findall(r'"`(.*?)`"', mermaid, re.S)
        self.assertEqual(mermaid.count("`"), 2 * len(labels), mermaid)
        self.assertTrue(all("`" not in label for label in labels))
        self.assertIn("Serves 'GET /books'", mermaid)


class MarkdownProseTest(unittest.TestCase):
    """Report prose is Markdown, not Mermaid: it must not carry #lt; / #gt;."""

    def test_flow_intro_and_heading_keep_plain_angle_brackets(self):
        section = render_c4._section(
            "#### Flow <main>", "c4-flow-x", "sequenceDiagram\n", None,
            intro="Handles <Request> objects",
        )
        self.assertIn("Handles <Request> objects", section)
        self.assertNotIn("#lt;", section)
        self.assertNotIn("#gt;", section)


class PlainLabelTest(unittest.TestCase):
    """Labels are plain, not Mermaid markdown strings.

    A markdown string ("`…`") makes mermaid parse the label as Markdown, which
    eats the metacharacters of ordinary code names: ``user_service`` loses its
    underscore and ``__main__`` turns bold. Escaping them does not help, because
    the SVG renderer drops the escapes. Plain labels parse no Markdown, so the
    characters survive. The cost is that the element name is no longer bold.
    """

    METACHAR_NAMES = ("user_service", "__main__", "2*3*4", "a~b")

    def test_element_labels_are_not_markdown_strings(self):
        model = _make_minimal_model(
            containers=[{"id": "svc", "name": "user_service", "technology": "Python",
                         "description": "runs __main__ and 2*3*4"}],
        )
        mermaid = render_c4.container_diagram(model)
        self.assertNotIn('"`', mermaid, f"markdown-string label in:\n{mermaid}")
        self.assertNotIn('`"', mermaid, f"markdown-string label in:\n{mermaid}")

    def test_metacharacters_survive_in_the_label(self):
        model = _make_minimal_model(
            containers=[{"id": "svc", "name": "user_service", "technology": "Python",
                         "description": "runs __main__ and 2*3*4 and a~b"}],
        )
        mermaid = render_c4.container_diagram(model)
        for name in self.METACHAR_NAMES:
            self.assertIn(name, mermaid,
                          f"{name!r} was altered in:\n{mermaid}")

    def test_no_bold_markers_are_emitted(self):
        model = _make_minimal_model(
            containers=[{"id": "svc", "name": "Svc", "technology": "Python"}],
        )
        mermaid = render_c4.container_diagram(model)
        self.assertNotIn("**", mermaid,
                         f"bold markers render literally in a plain label:\n{mermaid}")


class SequenceAliasEscapeTest(unittest.TestCase):
    """A ';' in a participant alias ends the statement and breaks the parse."""

    def test_semicolon_in_participant_alias_is_escaped(self):
        model = _make_minimal_model(
            people=[{"id": "user", "name": "User"}],
            containers=[{"id": "orders", "name": "Orders; API"}],
            flows=[{"name": "F", "steps": [
                {"from": "user", "to": "orders", "description": "post"},
            ]}],
        )
        _, _, mermaid, _ = render_c4.flow_diagrams(model, {"containers": []})[0]
        self.assertIn("participant orders as Orders#59; API", mermaid)
        self.assertNotIn("as Orders; API", mermaid)

    def test_hash_and_quote_in_participant_alias_are_escaped(self):
        model = _make_minimal_model(
            people=[{"id": "user", "name": 'Ops #1 "lead"'}],
            containers=[{"id": "svc", "name": "Svc"}],
            flows=[{"name": "F", "steps": [
                {"from": "user", "to": "svc", "description": "post"},
            ]}],
        )
        _, _, mermaid, _ = render_c4.flow_diagrams(model, {"containers": []})[0]
        self.assertIn("as Ops #35;1 #quot;lead#quot;", mermaid)


@unittest.skipUnless(os.environ.get("C4_REAL_RENDER") == "1",
                     "set C4_REAL_RENDER=1 to render with the real mermaid-cli")
class AdversarialCorpusTest(unittest.TestCase):
    """Reserved words, separators and special characters render with the real, pinned mermaid-cli."""

    def test_adversarial_corpus_renders(self):
        from scripts import svg_render

        model = _make_minimal_model(
            people=[{"id": "box", "name": "Box Person"}, {"id": "note", "name": "Note User"}],
            containers=[
                {"id": "end", "name": "End Service", "technology": "Python"},
                {"id": "graph", "name": "Graph \"Service\"", "technology": "Node.js"},
                {"id": "graph-api", "name": "Graph API `v2`", "technology": "Go"},
            ],
            external_systems=[{"id": "style", "name": "Style <Ext>", "technology": ""}],
            relationships=[
                {"from": "box", "to": "end", "description": "retry #3; ok"},
                {"from": "note", "to": "graph", "description": "Uses *special* text"},
                {"from": "end", "to": "graph-api", "description": "Calls"},
            ],
            flows=[{"name": "Adversarial flow", "steps": [
                {"from": "box", "to": "end", "description": "retry #3; ok"},
                {"from": "end", "to": "graph", "description": "Orders; API"},
            ]}],
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            diagrams = {
                "c4-context": render_c4.context_diagram(model),
                "c4-container": render_c4.container_diagram(model),
            }
            stem, _, flow, _ = render_c4.flow_diagrams(model, {"containers": []})[0]
            diagrams[stem] = flow
            for name, text in diagrams.items():
                (out / f"{name}.mmd").write_text(text, encoding="utf-8")
            results = svg_render.render([(name, out / f"{name}.mmd") for name in diagrams], out)
            self.assertEqual({r.stem: r.status for r in results}, {name: "ok" for name in diagrams},
                             [r for r in results if r.status != "ok"])
            container = _visible_text(out / "c4-container.svg")
            flow_text = _visible_text(out / f"{stem}.svg")
        for label in ("End Service", "Graph “Service”", "Graph API 'v2'", "Style &lt;Ext&gt;"):
            self.assertIn(label, container)
        self.assertIn("retry #3; ok", flow_text)


def _visible_text(svg):
    """The SVG's text nodes joined with spaces (labels are split into one tspan per word)."""
    words = re.findall(r">([^<>]+)<", Path(svg).read_text(encoding="utf-8"))
    return " ".join(" ".join(w.split()) for w in words if w.strip())

if __name__ == "__main__":
    unittest.main()
