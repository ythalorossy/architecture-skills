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
