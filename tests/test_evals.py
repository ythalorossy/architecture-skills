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


def model(**overrides):
    """A small candidate model; override any section for a specific case."""
    base = {
        "system": {"name": "Bookshop"},
        "people": [{"id": "reader", "name": "Reader"}],
        "containers": [
            {"id": "bookshop-web", "name": "Web app"},
            {"id": "bookshop-api", "name": "Bookshop API"},
            {"id": "db-postgresql", "name": "Orders database", "type": "database"},
            {"id": "db-elasticsearch", "name": "Catalogue index", "type": "database"},
        ],
        "external_systems": [{"id": "ext-payments", "name": "Payment provider"}],
        "relationships": [
            {"from": "reader", "to": "bookshop-web"},
            {"from": "bookshop-web", "to": "bookshop-api"},
            {"from": "bookshop-api", "to": "db-postgresql"},
            {"from": "bookshop-api", "to": "db-elasticsearch"},
            {"from": "bookshop-api", "to": "ext-payments"},
        ],
        "components": {
            "bookshop-web": {"web/src/api": "Fetch wrappers"},
            "bookshop-api": {"bookshop.orders": "Places an order"},
        },
        "flows": [{"id": "place-order", "name": "Buy", "steps": [
            {"from": "bookshop.orders", "to": "ext-payments"},
            {"from": "bookshop.orders", "to": "db-postgresql"},
        ]}],
    }
    base.update(overrides)
    return base


class TestResolveRoles(unittest.TestCase):
    def setUp(self):
        self.gold = grade.load_gold(GOLD_FILE)

    def test_every_role_resolves_on_a_good_model(self):
        matched = grade.resolve_roles(model(), self.gold)
        self.assertEqual(matched, {
            "reader": "reader",
            "web-ui": "bookshop-web",
            "api": "bookshop-api",
            "orders-db": "db-postgresql",
            "catalogue-index": "db-elasticsearch",
            "payments": "ext-payments",
        })

    def test_a_synonym_name_still_matches(self):
        candidate = model(containers=[
            {"id": "c1", "name": "Storefront"},
            {"id": "c2", "name": "Backend"},
        ])
        matched = grade.resolve_roles(candidate, self.gold)
        self.assertEqual(matched.get("web-ui"), "c1")
        self.assertEqual(matched.get("api"), "c2")

    def test_one_element_cannot_satisfy_two_roles(self):
        """'Bookshop API Web' matches both web-ui and api; it may claim one."""
        candidate = model(containers=[{"id": "only", "name": "Bookshop API Web"}])
        matched = grade.resolve_roles(candidate, self.gold)
        claimed = [role for role, element_id in matched.items() if element_id == "only"]
        self.assertEqual(len(claimed), 1, matched)
        self.assertEqual(claimed, ["web-ui"], "gold order decides: web-ui is listed first")

    def test_the_id_is_matched_as_well_as_the_name(self):
        candidate = model(containers=[{"id": "bookshop-api", "name": "Service"}])
        self.assertEqual(grade.resolve_roles(candidate, self.gold).get("api"), "bookshop-api")

    def test_matching_is_case_insensitive(self):
        candidate = model(containers=[{"id": "x", "name": "ELASTICSEARCH"}])
        self.assertEqual(grade.resolve_roles(candidate, self.gold).get("catalogue-index"), "x")

    def test_an_empty_model_resolves_nothing(self):
        self.assertEqual(grade.resolve_roles({}, self.gold), {})

    def test_a_non_dict_element_is_skipped(self):
        candidate = model(containers=["oops", {"id": "bookshop-api", "name": "API"}])
        self.assertEqual(grade.resolve_roles(candidate, self.gold).get("api"), "bookshop-api")

    def test_an_element_without_an_id_cannot_claim_a_role(self):
        for bad_id in ({}, {"id": ""}):
            with self.subTest(bad_id=bad_id):
                candidate = model(containers=[
                    {"name": "Bookshop API", **bad_id},
                    {"id": "real-api", "name": "API"},
                ])
                matched = grade.resolve_roles(candidate, self.gold)
                self.assertEqual(matched.get("api"), "real-api")
                self.assertNotIn(None, matched.values())

    def test_document_order_and_first_match_decide(self):
        gold = {"required_elements": [{"role": "api", "match": ["api"]}]}
        containers = [{"id": "c1", "name": "API one"}, {"id": "c2", "name": "API two"}]
        person = {"id": "p1", "name": "API user"}
        self.assertEqual(grade.resolve_roles({"containers": containers}, gold), {"api": "c1"})
        both = {"people": [person], "containers": containers}
        self.assertEqual(grade.resolve_roles(both, gold), {"api": "p1"}, "people come before containers")

    def test_match_terms_are_lowercased_too(self):
        gold = {"required_elements": [{"role": "api", "match": ["API"]}]}
        candidate = {"containers": [{"id": "c1", "name": "the api service"}]}
        self.assertEqual(grade.resolve_roles(candidate, gold), {"api": "c1"})


if __name__ == "__main__":
    unittest.main()
