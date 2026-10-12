"""
Unit tests for the eval grader (evals/grade.py).

Every case runs on canned dicts or on the committed bookshop fixture. None
calls a model, touches the network, or renders an SVG: `helpers` sets
C4_SVG=0 and the render-pass score passes svg=False.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT

EVALS = REPO_ROOT / "evals"
if str(EVALS) not in sys.path:
    sys.path.insert(0, str(EVALS))

import grade  # noqa: E402  (sys.path is set above)

from scripts.cli_support import UserError  # noqa: E402

GOLD_FILE = EVALS / "gold" / "bookshop.json"


def write_gold(root, gold):
    """Write a gold dict to a temp file and return its path."""
    path = Path(root) / "gold.json"
    path.write_text(json.dumps(gold), encoding="utf-8")
    return path


def minimal_gold(**overrides):
    """A small, well-formed gold; override any key for the malformed cases."""
    gold = {
        "repo": "tests/fixtures/repos/bookshop",
        "required_elements": [
            {"role": "api", "kind": "container", "match": ["api"]},
            {"role": "db", "kind": "database", "match": ["postgres"]},
        ],
        "required_relationships": [["api", "db"]],
        "required_flow_steps": [],
        "forbidden": ["redis"],
    }
    gold.update(overrides)
    return gold


class TestLoadGold(unittest.TestCase):
    def test_the_committed_gold_is_well_formed(self):
        gold = grade.load_gold(GOLD_FILE)
        roles = [element["role"] for element in gold["required_elements"]]
        self.assertEqual(len(roles), len(set(roles)))

    def test_duplicate_role_is_rejected(self):
        bad = minimal_gold(required_elements=[
            {"role": "api", "kind": "container", "match": ["api"]},
            {"role": "api", "kind": "container", "match": ["backend"]},
        ])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UserError) as caught:
                grade.load_gold(write_gold(tmp, bad))
        self.assertIn("duplicate role", str(caught.exception))
        self.assertIn("api", str(caught.exception))

    def test_a_relationship_end_that_is_not_a_role_is_rejected(self):
        bad = minimal_gold(required_relationships=[["api", "cache"]])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UserError) as caught:
                grade.load_gold(write_gold(tmp, bad))
        self.assertIn("cache", str(caught.exception))
        self.assertIn("not a declared role", str(caught.exception))

    def test_a_flow_step_end_that_is_not_a_role_is_rejected(self):
        bad = minimal_gold(required_flow_steps=[["api", "queue"]])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UserError) as caught:
                grade.load_gold(write_gold(tmp, bad))
        self.assertIn("queue", str(caught.exception))

    def test_two_roles_sharing_a_match_term_are_rejected(self):
        """Review Focus 4: shared terms make role resolution order-dependent."""
        bad = minimal_gold(required_elements=[
            {"role": "api", "kind": "container", "match": ["api"]},
            {"role": "gateway", "kind": "container", "match": ["api"]},
        ], required_relationships=[])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UserError) as caught:
                grade.load_gold(write_gold(tmp, bad))
        self.assertIn("api", str(caught.exception))
        self.assertIn("both", str(caught.exception))

    def test_a_forbidden_term_overlapping_a_match_term_is_rejected(self):
        bad = minimal_gold(forbidden=["postgres"])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UserError) as caught:
                grade.load_gold(write_gold(tmp, bad))
        self.assertIn("overlaps", str(caught.exception))

    def test_an_empty_required_elements_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UserError) as caught:
                grade.load_gold(write_gold(tmp, minimal_gold(required_elements=[])))
        self.assertIn("required_elements is empty", str(caught.exception))

    def test_malformed_json_names_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gold.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(UserError) as caught:
                grade.load_gold(path)
        self.assertIn("not valid JSON", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
