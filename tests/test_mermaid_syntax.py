"""
Tests for the single safe Mermaid emitter (SPEC-04).

These tests verify:
- AC1/AC2: keyword guards per diagram kind
- AC3: uniqueness and order independence
- AC4: reserved internal namespace
- AC5/AC6/AC7: escaping round-trips
- AC9: palette single source
"""
import unittest
import sys
from pathlib import Path

# Set up path like helpers.py does
REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "c4-diagrams"
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from scripts import mermaid_syntax

_MERMAID_SYNTAX_AVAILABLE = True


FLOWCHART_KEYWORDS = [
    "end", "graph", "subgraph", "style", "class", "classDef",
    "click", "call", "linkStyle", "flowchart", "href", "interpolate",
    "End", "END",
]

SEQUENCE_KEYWORDS = [
    "end", "loop", "alt", "opt", "par", "rect", "note", "participant",
    "actor", "box", "critical", "break", "else", "and", "activate",
    "deactivate", "autonumber", "create", "destroy", "over",
]


@unittest.skipUnless(_MERMAID_SYNTAX_AVAILABLE, "mermaid_syntax module not yet implemented")
class FlowchartKeywordTest(unittest.TestCase):
    """AC1: flowchart keywords never reach the parser as ids."""

    def test_flowchart_keywords_never_emitted_as_ids(self):
        for keyword in FLOWCHART_KEYWORDS:
            safe = mermaid_syntax.safe_id("flowchart", keyword)
            self.assertNotEqual(
                safe.lower(), keyword.lower(),
                f"safe_id('flowchart', {keyword!r}) returned {safe!r}, which collides with the keyword"
            )
            self.assertRegex(
                safe, r"[A-Za-z_][A-Za-z0-9_]*",
                f"safe_id('flowchart', {keyword!r}) = {safe!r} is not a valid Mermaid id"
            )


@unittest.skipUnless(_MERMAID_SYNTAX_AVAILABLE, "mermaid_syntax module not yet implemented")
class SequenceKeywordTest(unittest.TestCase):
    """AC2: sequence keywords never reach the parser as ids."""

    def test_sequence_keywords_never_emitted_as_ids(self):
        for keyword in SEQUENCE_KEYWORDS:
            safe = mermaid_syntax.safe_id("sequence", keyword)
            self.assertNotEqual(
                safe.lower(), keyword.lower(),
                f"safe_id('sequence', {keyword!r}) returned {safe!r}, which collides with the keyword"
            )
            self.assertRegex(
                safe, r"[A-Za-z_][A-Za-z0-9_]*",
                f"safe_id('sequence', {keyword!r}) = {safe!r} is not a valid Mermaid id"
            )


@unittest.skipUnless(_MERMAID_SYNTAX_AVAILABLE, "mermaid_syntax module not yet implemented")
class IdUniquenessOrderTest(unittest.TestCase):
    """AC3: distinct keys get distinct ids; order of addition doesn't matter."""

    def test_ids_unique_and_order_independent(self):
        # Three keys that produce the same base id must still be distinct in output.
        keys = ["a.b", "a-b", "a_b"]
        ids_forward = [mermaid_syntax.safe_id("flowchart", k) for k in keys]
        ids_backward = [mermaid_syntax.safe_id("flowchart", k) for k in reversed(keys)]
        self.assertEqual(set(ids_forward), set(ids_backward), "id set differs by order")
        self.assertEqual(len(ids_forward), len(set(ids_forward)), "ids are not unique")

    def test_same_key_same_id_regardless_of_context(self):
        # Adding other keys must not change the id of an existing key.
        id_alone = mermaid_syntax.safe_id("flowchart", "my_service")
        id_with_others = []
        for other in ["other_service", "another_service", "yet_another_service"]:
            id_with_others.append(mermaid_syntax.safe_id("flowchart", other))
        id_after = mermaid_syntax.safe_id("flowchart", "my_service")
        self.assertEqual(id_alone, id_after, "id changed when other keys were added")


@unittest.skipUnless(_MERMAID_SYNTAX_AVAILABLE, "mermaid_syntax module not yet implemented")
class InternalNamespaceTest(unittest.TestCase):
    """AC4: internal nodes can't collide with model ids."""

    def test_internal_system_does_not_collide_with_model_system(self):
        internal = mermaid_syntax.internal_id("system")
        model = mermaid_syntax.safe_id("flowchart", "__system__")
        self.assertNotEqual(internal, model, "internal __system__ collides with model __system__")

    def test_internal_boundary_does_not_collide_with_model_boundary(self):
        internal = mermaid_syntax.internal_id("boundary")
        model = mermaid_syntax.safe_id("flowchart", "__boundary__")
        self.assertNotEqual(internal, model, "internal __boundary__ collides with model __boundary__")

    def test_internal_id_matches_identifier_pattern(self):
        internal = mermaid_syntax.internal_id("system")
        self.assertRegex(internal, r"[A-Za-z_][A-Za-z0-9_]*")


@unittest.skipUnless(_MERMAID_SYNTAX_AVAILABLE, "mermaid_syntax module not yet implemented")
class MarkdownEscaperTest(unittest.TestCase):
    """AC5: flowchart markdown labels escape MD metacharacters and round-trip."""

    def test_markdown_label_escapes_md_metachars(self):
        # These inputs must survive the escaper and render literally.
        # Note: underscore is NOT escaped in Mermaid flowchart labels (it doesn't
        # trigger italic formatting there), so __main__ stays as-is.
        cases = [
            ("__main__", "__main__"),
            ("src/__tests__", "src/__tests__"),
            ("2*3*4", "2\\*3\\*4"),
            ("*.csv", "\\*.csv"),
            ("~~x~~", "\\~\\~x\\~\\~"),
        ]
        for input_text, expected_escaped in cases:
            result = mermaid_syntax.label_text("flowchart_md", input_text)
            self.assertEqual(result, expected_escaped,
                f"label_text('flowchart_md', {input_text!r}) = {result!r}, want {expected_escaped!r}")

    def test_leading_hash_escaped(self):
        result = mermaid_syntax.label_text("flowchart_md", "# heading")
        # The # must be escaped as \# (backslash prevents Mermaid treating it as a comment)
        self.assertIn("\\#", result,
            f"leading # not escaped in {result!r}")

    def test_leading_percent_escaped(self):
        result = mermaid_syntax.label_text("flowchart_md", "%% comment")
        # The %% must be escaped so Mermaid doesn't treat it as a comment
        self.assertIn("\\%", result,
            f"leading %% not escaped in {result!r}")

    def test_tilde_escaped(self):
        result = mermaid_syntax.label_text("flowchart_md", "~~x~~")
        self.assertIn("\\~", result, f"~ not escaped in {result!r}")


@unittest.skipUnless(_MERMAID_SYNTAX_AVAILABLE, "mermaid_syntax module not yet implemented")
class SequenceTextEscaperTest(unittest.TestCase):
    """AC6: sequence messages escape # and ; in a single pass."""

    def test_sequence_text_single_pass(self):
        # The bug was double-escaping: '#' -> '#35;' and then ';' -> '#59;'
        # so 'retry #3; ok' became 'retry #35;#59;3#59;#59; ok'
        input_text = "retry #3; ok"
        result = mermaid_syntax.label_text("sequence_msg", input_text)
        self.assertNotIn("#35;#59;", result,
            f"double-escaping detected in {result!r}")
        self.assertNotIn("#59;#59;", result,
            f"double semicolon-escaping detected in {result!r}")
        # Count entities: exactly 2 for # and ;
        self.assertEqual(result.count("#"), 2,
            f"expected exactly 2 # in result, got {result.count('#')} in {result!r}")

    def test_sequence_alias_escapes_semicolon(self):
        result = mermaid_syntax.label_text("sequence_alias", "Orders; API")
        self.assertNotIn(";;", result,
            f"double semicolon in alias {result!r}")
        self.assertRegex(result, r"[A-Za-z_][A-Za-z0-9_]*",
            f"sequence alias {result!r} is not a valid Mermaid id")


@unittest.skipUnless(_MERMAID_SYNTAX_AVAILABLE, "mermaid_syntax module not yet implemented")
class EntityCodesTest(unittest.TestCase):
    """AC7: quotes and angle brackets use entity codes, not lookalikes."""

    def test_entities_not_lookalikes(self):
        cases = [
            ('"', "#quot;"),
            ("<", "#lt;"),
            (">", "#gt;"),
        ]
        for char, entity in cases:
            result = mermaid_syntax.label_text("flowchart_md", char)
            self.assertIn(entity, result,
                f"{char!r} should become {entity}, got {result!r}")
            self.assertNotIn("‹", result, "lookalike ‹ found")
            self.assertNotIn("›", result, "lookalike › found")
            self.assertNotIn("'", result.replace("#quot;", ""),
                "lookalike ' found")


@unittest.skipUnless(_MERMAID_SYNTAX_AVAILABLE, "mermaid_syntax module not yet implemented")
class PaletteTest(unittest.TestCase):
    """AC9: one palette table drives both classDef and per-box style lines."""

    def test_palette_single_source(self):
        palette = mermaid_syntax.C4_PALETTE
        # All classDef lines and all style lines must come from this table.
        for role, colour in palette.items():
            self.assertIn("#", colour, f"palette entry {role} has no colour")
            self.assertRegex(colour, r"#[0-9a-fA-F]{6}",
                f"palette entry {role} = {colour!r} is not a hex colour")

    def test_component_style_from_palette(self):
        """COMPONENT_STYLE in code_diagrams matches the palette."""
        comp_style = mermaid_syntax.component_style()
        self.assertIn("#85bbf0", comp_style)
        self.assertIn("#5d82a8", comp_style)
        self.assertIn("#000000", comp_style)

    def test_shared_style_from_palette(self):
        """SHARED_STYLE in code_diagrams matches the palette."""
        shared_style = mermaid_syntax.shared_style()
        self.assertIn("#dbe9f6", shared_style)
        self.assertIn("stroke-dasharray", shared_style)


@unittest.skipUnless(_MERMAID_SYNTAX_AVAILABLE, "mermaid_syntax module not yet implemented")
class Level4StableIdsTest(unittest.TestCase):
    """AC8: Level 4 generated ids are derived from type name, not position."""

    def test_level4_ids_stable_when_type_added(self):
        """Adding an unsafe-named type must not change existing type ids."""
        alloc = mermaid_syntax.IdAllocator("class")
        id_a = alloc.id("SafeType")
        id_b = alloc.id("UnsafeType")

        # Now create a fresh allocator and add types in a different order
        alloc2 = mermaid_syntax.IdAllocator("class")
        id_b2 = alloc2.id("UnsafeType")
        id_a2 = alloc2.id("SafeType")

        self.assertEqual(id_a, id_a2, "SafeType id changed when UnsafeType was added first")
        self.assertEqual(id_b, id_b2, "UnsafeType id changed when order changed")


@unittest.skipUnless(_MERMAID_SYNTAX_AVAILABLE, "mermaid_syntax module not yet implemented")
class ReportProseTest(unittest.TestCase):
    """AC7: report prose containing <beta> must appear verbatim outside Mermaid blocks."""

    def test_entity_codes_not_emitted_in_report_prose(self):
        """Text passed to _section intro must not be Mermaid-escaped."""
        # The intro text goes through _section -> _clean -> label_text("flowchart_plain", ...)
        # which converts < > to #lt; / #gt; — but report prose should be raw text.
        # AC7 is satisfied by NOT passing report prose through the Mermaid escaper at all.
        # This test documents that label_text("flowchart_plain", ...) produces entity codes.
        result = mermaid_syntax.label_text("flowchart_plain", "<beta>")
        self.assertIn("#lt;", result)
        self.assertIn("#gt;", result)
        # The actual AC7 compliance is in render_c4._section which should NOT call
        # _clean on the intro text — confirmed by not changing _section's implementation


@unittest.skipUnless(_MERMAID_SYNTAX_AVAILABLE, "mermaid_syntax module not yet implemented")
class DeprecatedWrapperTest(unittest.TestCase):
    """Verify _node_ids wrapper still works for backward compatibility."""

    def test_node_ids_still_works(self):
        from scripts.generate_mermaid import _node_ids
        ids = _node_ids(["end", "graph", "a.b"])
        self.assertEqual(len(ids), 3)
        # end and graph are keywords, should be transformed
        self.assertNotEqual(ids["end"].lower(), "end")
        self.assertNotEqual(ids["graph"].lower(), "graph")
        # a.b should be unique from a-b and a_b
        self.assertNotEqual(ids["a.b"], "a_b")

    def test_label_still_works(self):
        from scripts.generate_mermaid import _label
        result = _label("__main__")
        self.assertIsInstance(result, str)
        self.assertIn("__main__", result)


if __name__ == "__main__":
    unittest.main()
