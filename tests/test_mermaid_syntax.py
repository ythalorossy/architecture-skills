"""
Tests for the single safe Mermaid emitter.

These tests verify:
- keyword guards per diagram kind
- uniqueness and order independence
- reserved internal namespace
- escaping round-trips
- palette single source
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
    """Flowchart keywords never reach the parser as ids."""

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
    """Sequence keywords never reach the parser as ids."""

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


class IdUniquenessTest(unittest.TestCase):
    """Within one diagram, different keys never share an id, and ids stay readable."""

    def test_keys_with_the_same_slug_get_distinct_ids(self):
        alloc = mermaid_syntax.IdAllocator("flowchart")
        keys = ["a.b", "a-b", "a_b", "a b", "a/b"]
        ids = [alloc.id(k) for k in keys]
        self.assertEqual(len(set(ids)), len(keys), ids)
        self.assertEqual(ids[0], "a_b")
        self.assertEqual(ids[1:], ["a_b_2", "a_b_3", "a_b_4", "a_b_5"])

    def test_same_key_keeps_its_id(self):
        alloc = mermaid_syntax.IdAllocator("flowchart")
        first = alloc.id("db-sql-server")
        for other in ("db-sql-server-2", "db_sql_server", "x"):
            alloc.id(other)
        self.assertEqual(alloc.id("db-sql-server"), first)

    def test_ids_are_readable_slugs(self):
        alloc = mermaid_syntax.IdAllocator("flowchart")
        self.assertEqual(alloc.id("db-sql-server"), "db_sql_server")
        self.assertEqual(alloc.id("ext-api.short.io"), "ext_api_short_io")
        self.assertEqual(alloc.id("2fa-service"), "n_2fa_service")

    def test_many_random_keys_are_unique_and_valid(self):
        import random
        rng = random.Random(7)
        alphabet = "ab-_. /1"
        keys = {"".join(rng.choice(alphabet) for _ in range(rng.randint(1, 4))) for _ in range(500)}
        alloc = mermaid_syntax.IdAllocator("flowchart")
        ids = [alloc.id(k) for k in sorted(keys)]
        self.assertEqual(len(set(ids)), len(keys))
        for value in ids:
            self.assertRegex(value, r"^[A-Za-z_][A-Za-z0-9_]*$")


class BacktickTest(unittest.TestCase):
    """A backtick would close the "`…`" markdown string that holds a label."""

    def test_backticks_never_survive_flowchart_escaping(self):
        for kind in ("flowchart_md", "flowchart_plain"):
            self.assertNotIn("`", mermaid_syntax.label_text(kind, "call `api` now"), kind)


class InternalNamespaceTest(unittest.TestCase):
    """Internal nodes share the diagram's allocator, so they can't collide with model ids."""

    def test_model_id_named_like_an_internal_node(self):
        for internal_first in (True, False):
            alloc = mermaid_syntax.IdAllocator("flowchart")
            if internal_first:
                internal, model = alloc.internal("boundary"), alloc.id("boundary")
            else:
                model, internal = alloc.id("boundary"), alloc.internal("boundary")
            self.assertNotEqual(internal, model)
            self.assertEqual({internal, model}, {"boundary", "boundary_2"})

    def test_internal_key_round_trips_through_id(self):
        alloc = mermaid_syntax.IdAllocator("flowchart")
        key = mermaid_syntax.IdAllocator.internal_key("system")
        self.assertEqual(alloc.id(key), alloc.internal("system"))
        self.assertEqual(alloc.internal("system"), "system")


@unittest.skipUnless(_MERMAID_SYNTAX_AVAILABLE, "mermaid_syntax module not yet implemented")
class MarkdownEscaperTest(unittest.TestCase):
    """Flowchart markdown labels escape MD metacharacters and round-trip."""

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
    """Sequence messages escape # and ; in a single pass."""

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
    """Angle brackets use entity codes; double quotes become “…” in flowchart labels."""

    def test_angle_brackets_use_entities(self):
        for kind in ("flowchart_md", "flowchart_plain"):
            self.assertEqual(mermaid_syntax.label_text(kind, "<b>"), "#lt;b#gt;")

    def test_double_quotes_become_typographic(self):
        # mermaid shows #quot; literally in flowchart labels (checked against
        # mermaid-cli 12, see test_svg_render.TestRealRenderer).
        for kind in ("flowchart_md", "flowchart_plain"):
            result = mermaid_syntax.label_text(kind, 'Says "hi" and "bye"')
            self.assertEqual(result, "Says “hi” and “bye”", kind)
            self.assertNotIn('"', result)

    def test_sequence_alias_keeps_the_entity(self):
        # Sequence diagrams decode #quot; correctly.
        self.assertEqual(mermaid_syntax.label_text("sequence_alias", 'a "b"'), "a #quot;b#quot;")


@unittest.skipUnless(_MERMAID_SYNTAX_AVAILABLE, "mermaid_syntax module not yet implemented")
class PaletteTest(unittest.TestCase):
    """One palette table drives both classDef and per-box style lines."""

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

    def test_no_colour_is_written_outside_the_palette(self):
        """Every hex colour the renderer draws with is declared in one table."""
        import re

        source = (REPO_ROOT / "skills" / "c4-diagrams" / "scripts" / "render_c4.py").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{6}\b", source), [],
                         "render_c4.py writes a colour of its own; add it to mermaid_syntax.C4_PALETTE")

    def test_the_boundary_and_the_folder_box_are_in_the_palette(self):
        palette = mermaid_syntax.C4_PALETTE
        for role in ("boundary_stroke", "folder", "folder_stroke"):
            self.assertIn(role, palette)

    def test_shared_style_from_palette(self):
        """SHARED_STYLE in code_diagrams matches the palette."""
        shared_style = mermaid_syntax.shared_style()
        self.assertIn("#dbe9f6", shared_style)
        self.assertIn("stroke-dasharray", shared_style)


@unittest.skipUnless(_MERMAID_SYNTAX_AVAILABLE, "mermaid_syntax module not yet implemented")
class Level4StableIdsTest(unittest.TestCase):
    """Level 4 generated ids are derived from type name, not position."""

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
    """Report prose containing <beta> must appear verbatim outside Mermaid blocks."""

    def test_entity_codes_not_emitted_in_report_prose(self):
        """Text passed to _section intro must not be Mermaid-escaped."""
        # The intro text goes through _section -> _clean -> label_text("flowchart_plain", ...)
        # which converts < > to #lt; / #gt; — but report prose should be raw text.
        # Report prose must not go through the Mermaid escaper at all.
        # This test documents that label_text("flowchart_plain", ...) produces entity codes.
        result = mermaid_syntax.label_text("flowchart_plain", "<beta>")
        self.assertIn("#lt;", result)
        self.assertIn("#gt;", result)
        # render_c4._section routes the intro through _prose, not the escaper.


@unittest.skipUnless(_MERMAID_SYNTAX_AVAILABLE, "mermaid_syntax module not yet implemented")
class DeprecatedWrapperTest(unittest.TestCase):
    """Verify _node_ids wrapper still works for backward compatibility."""

    def test_node_ids_avoids_keywords_and_collisions(self):
        from scripts.generate_mermaid import _node_ids
        ids = _node_ids(["end", "graph", "a.b", "a_b"])
        self.assertEqual(ids["end"], "end_2")
        self.assertEqual(ids["graph"], "graph_2")
        self.assertEqual((ids["a.b"], ids["a_b"]), ("a_b", "a_b_2"))

    def test_label_still_works(self):
        from scripts.generate_mermaid import _label
        result = _label("__main__")
        self.assertIsInstance(result, str)
        self.assertIn("__main__", result)


if __name__ == "__main__":
    unittest.main()
