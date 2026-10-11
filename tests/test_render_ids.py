"""
Tests for safe Mermaid rendering with adversarial identifiers (SPEC-04).

tests/test_render_ids.py verifies:
- AC4: person named __system__ keeps both nodes
- AC4: container named __boundary__ is drawn
- AC11: adversarial corpus parses with mmdc (optional, skipped without mmdc)

The module under test is the existing render_c4 module, which will call mermaid_syntax
once implemented.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import write


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
    """AC4: a person with id __system__ must not collide with the internal __system__ node."""

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
    """AC4: a container with id __boundary__ must not collide with the internal boundary node."""

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


class AdversarialCorpusTest(unittest.TestCase):
    """AC11: adversarial corpus renders with mmdc and SVG contains expected labels."""

    def test_adversarial_corpus_parses_with_mmdc(self):
        if shutil.which("mmdc") is None:
            self.skipTest("mmdc not available")

        # Build a model with every problematic identifier.
        model = _make_minimal_model(
            people=[
                {"id": "box", "name": "Box Person"},
                {"id": "note", "name": "Note User"},
            ],
            containers=[
                {"id": "end", "name": "End Service", "technology": "Python"},
                {"id": "graph", "name": "Graph Service", "technology": "Node.js"},
            ],
            external_systems=[
                {"id": "style", "name": "Style Ext", "technology": ""},
            ],
            relationships=[
                {"from": "box", "to": "end", "description": "retry #3; ok"},
                {"from": "note", "to": "graph", "description": "Uses *special* text"},
            ],
            flows=[{
                "name": "Adversarial flow",
                "steps": [
                    {"from": "box", "to": "end", "description": "retry #3; ok"},
                    {"from": "end", "to": "graph", "description": "Orders; API"},
                ]
            }],
        )

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)

            # Render context diagram
            ctx = render_c4.context_diagram(model)
            (output / "c4-context.mmd").write_text(ctx, encoding="utf-8")

            # Render flow diagram
            flows = render_c4.flow_diagrams(model, {})
            self.assertGreater(len(flows), 0)
            stem, _, flow_mmd, _ = flows[0]
            (output / f"{stem}.mmd").write_text(flow_mmd, encoding="utf-8")

            import subprocess
            for mmd_file in output.glob("*.mmd"):
                result = subprocess.run(
                    ["mmdc", "-i", str(mmd_file), "-o", str(mmd_file.with_suffix(".svg"))],
                    capture_output=True, timeout=30
                )
                self.assertEqual(result.returncode, 0,
                    f"mmdc failed on {mmd_file.name}:\n{result.stderr.decode()}")

                svg_text = mmd_file.with_suffix(".svg").read_text(encoding="utf-8")
                # Verify the labels are actually in the SVG
                self.assertIn("box", svg_text, f"label 'box' missing from SVG")
                self.assertIn("retry", svg_text, f"label 'retry' missing from SVG")


if __name__ == "__main__":
    unittest.main()
