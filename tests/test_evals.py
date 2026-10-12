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


class TestRecall(unittest.TestCase):
    def setUp(self):
        self.gold = grade.load_gold(GOLD_FILE)

    def test_a_complete_model_scores_one(self):
        result = grade.score_recall(model(), self.gold)
        self.assertEqual(result["score"], 1.0)
        self.assertEqual(result["hits"], 13)
        self.assertEqual(result["total"], 13)
        self.assertEqual(result["parts"]["elements"], (6, 6))
        self.assertEqual(result["parts"]["relationships"], (5, 5))
        self.assertEqual(result["parts"]["flow_steps"], (2, 2))
        self.assertEqual(result["missed"], [])

    def test_a_component_key_that_collides_with_a_container_id_resolves_to_its_owner(self):
        """The owner mapping runs before the role lookup, so the component wins."""
        candidate = model(
            components={"bookshop-web": {"bookshop-api": "A module that shares the API's id"}},
            flows=[{"id": "f", "name": "F", "steps": [{"from": "bookshop-api", "to": "db-postgresql"}]}],
        )
        result = grade.score_recall(candidate, self.gold)
        self.assertIn("flow step api -> orders-db", result["missed"])
        step_pairs = grade._edge_roles(
            grade._flow_steps(candidate), grade._role_of(grade.resolve_roles(candidate, self.gold)),
            grade._component_owner(candidate))
        self.assertEqual(step_pairs, {("web-ui", "orders-db")})

    def test_deleting_the_api_container_cascades(self):
        """Every gold role is a relationship end, so an element loss is never alone."""
        candidate = model(containers=[
            {"id": "bookshop-web", "name": "Web app"},
            {"id": "db-postgresql", "name": "Orders database", "type": "database"},
            {"id": "db-elasticsearch", "name": "Catalogue index", "type": "database"},
        ])
        result = grade.score_recall(candidate, self.gold)
        self.assertEqual(result["parts"]["elements"], (5, 6))
        # Only reader -> web-ui survives: the other four all have the API as an end.
        self.assertEqual(result["parts"]["relationships"], (1, 5))
        # Both required steps run through bookshop.orders, a module of the API.
        self.assertEqual(result["parts"]["flow_steps"], (0, 2))
        self.assertIn("element api", result["missed"])
        self.assertIn("relationship web-ui -> api", result["missed"])

    def test_a_reversed_relationship_does_not_match(self):
        candidate = model(relationships=[{"from": "db-postgresql", "to": "bookshop-api"}])
        result = grade.score_recall(candidate, self.gold)
        self.assertIn("relationship api -> orders-db", result["missed"])

    def test_a_model_without_flows_or_components_scores_zero_flow_steps(self):
        """Review Focus 2: every facts-only model has this shape."""
        candidate = model()
        del candidate["flows"]
        del candidate["components"]
        result = grade.score_recall(candidate, self.gold)
        self.assertEqual(result["parts"]["flow_steps"], (0, 2))
        self.assertEqual(result["parts"]["elements"], (6, 6))

    def test_an_end_that_is_missing_or_none_is_skipped(self):
        """Review Focus 3: a half-written model scores, it does not crash."""
        candidate = model(
            relationships=[{"from": None, "to": "bookshop-api"}, {"to": "db-postgresql"},
                           {"from": "bookshop-api", "to": "db-postgresql"}],
            flows=[{"id": "f", "name": "F", "steps": [{"from": "bookshop.orders"}, "oops"]}],
        )
        result = grade.score_recall(candidate, self.gold)
        self.assertEqual(result["parts"]["relationships"], (1, 5))
        self.assertEqual(result["parts"]["flow_steps"], (0, 2))

    def test_the_fixture_model_scores_one(self):
        """The grader's self-check against the committed reference answer."""
        fixture = json.loads(
            (REPO_ROOT / "tests" / "fixtures" / "repos" / "bookshop" / "c4-model.json")
            .read_text(encoding="utf-8"))
        result = grade.score_recall(fixture, self.gold)
        self.assertEqual(result["score"], 1.0, result["missed"])


class TestHallucination(unittest.TestCase):
    def setUp(self):
        self.gold = grade.load_gold(GOLD_FILE)

    def test_a_clean_model_has_none(self):
        result = grade.score_hallucination(model(), self.gold, [])
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["problems"], [])

    def test_a_forbidden_element_is_counted(self):
        candidate = model(containers=model()["containers"] + [{"id": "c", "name": "Redis cache"}])
        result = grade.score_hallucination(candidate, self.gold, [])
        self.assertEqual(result["count"], 1)
        self.assertIn("redis", result["problems"][0].lower())
        self.assertIn("Redis cache", result["problems"][0])

    def test_an_element_is_counted_once_however_many_terms_it_hits(self):
        candidate = model(containers=[{"id": "c", "name": "Redis and Kafka bus"}])
        self.assertEqual(grade.score_hallucination(candidate, self.gold, [])["count"], 1)

    def test_drift_from_validate_is_counted(self):
        drift = ["container 'ghost' is not in the facts"]
        result = grade.score_hallucination(model(), self.gold, drift)
        self.assertEqual(result["count"], 1)
        self.assertIn("ghost", result["problems"][0])

    def test_forbidden_and_drift_add_up(self):
        candidate = model(containers=model()["containers"] + [{"id": "c", "name": "Kafka"}])
        result = grade.score_hallucination(candidate, self.gold, ["drifted"])
        self.assertEqual(result["count"], 2)

    def test_forbidden_terms_are_lowercased_too(self):
        gold = {"forbidden": ["Redis"]}
        candidate = model(containers=[{"id": "c", "name": "redis cache"}])
        self.assertEqual(grade.score_hallucination(candidate, gold, [])["count"], 1)

    def test_the_fixture_model_has_none(self):
        """Verified against the real render(): status ok, no drift, no warnings."""
        fixture = json.loads(
            (REPO_ROOT / "tests" / "fixtures" / "repos" / "bookshop" / "c4-model.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(grade.score_hallucination(fixture, self.gold, [])["count"], 0)


BOOKSHOP = REPO_ROOT / "tests" / "fixtures" / "repos" / "bookshop"


class TestEvidence(unittest.TestCase):
    def test_real_evidence_scores_one(self):
        candidate = model(containers=[
            {"id": "bookshop-api", "name": "API",
             "evidence": ["api/bookshop/main.py:6", "docker-compose.yml:9"]},
        ])
        result = grade.score_evidence(candidate, BOOKSHOP)
        self.assertEqual(result["score"], 1.0)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["problems"], [])

    def test_a_file_that_does_not_exist_is_a_problem(self):
        candidate = model(containers=[{"id": "x", "name": "X", "evidence": ["nope/missing.py:1"]}])
        result = grade.score_evidence(candidate, BOOKSHOP)
        self.assertEqual(result["score"], 0.0)
        self.assertIn("nope/missing.py:1", result["problems"][0])

    def test_a_line_past_the_end_of_the_file_is_a_problem(self):
        candidate = model(containers=[
            {"id": "x", "name": "X",
             "evidence": ["api/bookshop/main.py:6", "api/bookshop/main.py:4000"]},
        ])
        result = grade.score_evidence(candidate, BOOKSHOP)
        self.assertEqual(result["valid"], 1)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["score"], 0.5)
        self.assertIn("4000", result["problems"][0])

    def test_a_model_with_no_evidence_scores_one_of_zero(self):
        """Review Focus: '1.0' must never be read as good when nothing was checked."""
        candidate = model(containers=[{"id": "x", "name": "X"}], people=[], external_systems=[])
        result = grade.score_evidence(candidate, BOOKSHOP)
        self.assertEqual(result["score"], 1.0)
        self.assertEqual(result["total"], 0)

    def test_evidence_with_a_note_is_understood(self):
        candidate = model(containers=[
            {"id": "x", "name": "X", "evidence": ["docker-compose.yml:9 (the api service)"]},
        ])
        self.assertEqual(grade.score_evidence(candidate, BOOKSHOP)["score"], 1.0)

    def test_the_fixture_model_evidence_is_all_valid(self):
        fixture = json.loads((BOOKSHOP / "c4-model.json").read_text(encoding="utf-8"))
        result = grade.score_evidence(fixture, BOOKSHOP)
        self.assertEqual(result["score"], 1.0, result["problems"])
        self.assertGreater(result["total"], 0)


if __name__ == "__main__":
    unittest.main()
