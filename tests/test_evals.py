"""
Unit tests for the eval grader (evals/grade.py).

Every case runs on canned dicts or on the committed bookshop fixture. None
calls a model, touches the network, or renders an SVG: `helpers` sets
C4_SVG=0 and the render-pass score passes svg=False.
"""
import json
import subprocess
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
        """Shared terms make role resolution order-dependent."""
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
        """A facts-only model has no flows or components, so it scores zero flow steps."""
        candidate = model()
        del candidate["flows"]
        del candidate["components"]
        result = grade.score_recall(candidate, self.gold)
        self.assertEqual(result["parts"]["flow_steps"], (0, 2))
        self.assertEqual(result["parts"]["elements"], (6, 6))

    def test_an_end_that_is_missing_or_none_is_skipped(self):
        """A half-written model scores, it does not crash."""
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
        """A score of 1.0 over zero entries must report total 0, so it is never read as good evidence."""
        candidate = model(containers=[{"id": "x", "name": "X"}], people=[], external_systems=[])
        result = grade.score_evidence(candidate, BOOKSHOP)
        self.assertEqual(result["score"], 1.0)
        self.assertEqual(result["total"], 0)

    def test_evidence_with_a_note_is_understood(self):
        candidate = model(containers=[
            {"id": "x", "name": "X", "evidence": ["docker-compose.yml:9 (the api service)"]},
        ])
        self.assertEqual(grade.score_evidence(candidate, BOOKSHOP)["score"], 1.0)

    def _single(self, evidence):
        candidate = model(containers=[{"id": "x", "name": "X", "evidence": evidence}])
        return grade.score_evidence(candidate, BOOKSHOP)

    def test_a_non_list_evidence_value_is_one_problem_not_a_crash(self):
        for bad, kind in (("api/bookshop/main.py:6", "str"), (5, "int"), ({"a": 1}, "dict")):
            with self.subTest(kind=kind):
                result = self._single(bad)
                self.assertEqual(result["total"], 1)
                self.assertEqual(result["score"], 0.0)
                self.assertIn(f"x: evidence is a {kind}, expected a list", result["problems"])

    def test_a_blank_entry_is_a_problem(self):
        for blank in ("", "   ", " (just a note)"):
            with self.subTest(blank=blank):
                result = self._single([blank])
                self.assertEqual((result["total"], result["score"]), (1, 0.0))
                self.assertIn("blank", result["problems"][0])

    def test_an_absolute_path_is_a_problem(self):
        for path in ("/etc/passwd", "/etc/passwd:1", "C:\\Windows\\win.ini"):
            with self.subTest(path=path):
                result = self._single([path])
                self.assertEqual(result["score"], 0.0)
                self.assertIn("absolute", result["problems"][0])

    def test_a_path_that_escapes_the_repository_is_a_problem(self):
        result = self._single(["../../etc/passwd"])
        self.assertEqual(result["score"], 0.0)
        self.assertIn("escapes", result["problems"][0])

    def test_a_non_string_entry_is_a_problem(self):
        result = self._single([7, None])
        self.assertEqual((result["total"], result["score"]), (2, 0.0))

    def test_an_absent_or_empty_evidence_list_counts_nothing(self):
        self.assertEqual(self._single([])["total"], 0)

    def test_the_fixture_model_evidence_is_all_valid(self):
        fixture = json.loads((BOOKSHOP / "c4-model.json").read_text(encoding="utf-8"))
        result = grade.score_evidence(fixture, BOOKSHOP)
        self.assertEqual(result["score"], 1.0, result["problems"])
        self.assertGreater(result["total"], 0)


from scripts import analyze_repository  # noqa: E402  (sys.path is set at the top)


def analyzed(tmp, model_text=None):
    """Run the analyzer on the bookshop fixture; optionally drop in a model."""
    output = Path(tmp) / "out"
    argv = sys.argv
    sys.argv = ["analyze_repository.py", str(BOOKSHOP), "--output", str(output), "--no-svg"]
    try:
        analyze_repository.main()
    except SystemExit:
        pass
    finally:
        sys.argv = argv
    if model_text is not None:
        (output / "c4-model.json").write_text(model_text, encoding="utf-8")
    return output


class TestRenderPass(unittest.TestCase):
    def test_the_fixture_model_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = analyzed(tmp, (BOOKSHOP / "c4-model.json").read_text(encoding="utf-8"))
            result = grade.score_render(output, BOOKSHOP)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["drift"], [])

    def test_an_invalid_model_does_not_pass(self):
        broken = json.dumps({
            "system": {"name": "X"},
            "containers": [{"id": "a", "name": "A"}],
            "relationships": [{"from": "a", "to": "ghost"}],
        })
        with tempfile.TemporaryDirectory() as tmp:
            result = grade.score_render(analyzed(tmp, broken), BOOKSHOP)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "invalid")
        self.assertTrue(any("ghost" in problem for problem in result["problems"]))

    def test_a_missing_facts_key_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = analyzed(tmp, (BOOKSHOP / "c4-model.json").read_text(encoding="utf-8"))
            facts = json.loads((output / "c4-facts.json").read_text(encoding="utf-8"))
            del facts["data_stores"]
            (output / "c4-facts.json").write_text(json.dumps(facts), encoding="utf-8")
            result = grade.score_render(output, BOOKSHOP)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "error")
        self.assertTrue(any("data_stores" in problem for problem in result["problems"]))

    def test_grading_does_not_touch_the_folder(self):
        """render() writes c4-*.mmd; a baseline folder must come back unchanged."""
        with tempfile.TemporaryDirectory() as tmp:
            output = analyzed(tmp, (BOOKSHOP / "c4-model.json").read_text(encoding="utf-8"))
            before = {path.name: path.read_bytes() for path in sorted(output.iterdir())
                      if path.is_file()}
            grade.score_render(output, BOOKSHOP)
            after = {path.name: path.read_bytes() for path in sorted(output.iterdir())
                     if path.is_file()}
        self.assertEqual(before.keys(), after.keys())
        self.assertEqual(before, after)


import contextlib  # noqa: E402
import io  # noqa: E402


class TestGrade(unittest.TestCase):
    def setUp(self):
        self.gold = grade.load_gold(GOLD_FILE)

    def test_the_fixture_model_scores_perfectly(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = analyzed(tmp, (BOOKSHOP / "c4-model.json").read_text(encoding="utf-8"))
            scores = grade.grade(output, self.gold, BOOKSHOP)
        self.assertEqual(scores["recall"]["score"], 1.0, scores["recall"]["missed"])
        self.assertEqual(scores["hallucination"]["count"], 0, scores["hallucination"]["problems"])
        self.assertEqual(scores["evidence"]["score"], 1.0, scores["evidence"]["problems"])
        self.assertTrue(scores["render"]["ok"])

    def test_an_output_folder_without_a_model_is_refused(self):
        """Review Focus 1: render() would fall back to the facts-only model."""
        with tempfile.TemporaryDirectory() as tmp:
            output = analyzed(tmp)
            (output / "c4-model.json").unlink(missing_ok=True)
            with self.assertRaises(UserError) as caught:
                grade.grade(output, self.gold, BOOKSHOP)
        self.assertIn("no c4-model.json", str(caught.exception))

    def test_a_malformed_model_names_the_file(self):
        """Review Focus 5: one ERROR line, no traceback."""
        with tempfile.TemporaryDirectory() as tmp:
            output = analyzed(tmp, "{not json")
            with self.assertRaises(UserError) as caught:
                grade.grade(output, self.gold, BOOKSHOP)
        self.assertIn("not valid JSON", str(caught.exception))

    def test_a_model_that_is_not_an_object_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = analyzed(tmp, "[1, 2, 3]")
            with self.assertRaises(UserError) as caught:
                grade.grade(output, self.gold, BOOKSHOP)
        self.assertIn("expected a JSON object", str(caught.exception))

    def test_the_report_names_what_was_missed(self):
        scores = {
            "recall": {"score": 0.5, "hits": 1, "total": 2,
                       "parts": {"elements": (1, 1), "relationships": (0, 1), "flow_steps": (0, 0)},
                       "missed": ["relationship api -> orders-db"]},
            "hallucination": {"count": 1, "problems": ["forbidden 'redis': Redis cache"]},
            "evidence": {"score": 0.5, "valid": 1, "total": 2, "problems": ["x.py:9: does not exist"]},
            "render": {"ok": True, "status": "ok", "problems": [], "drift": []},
        }
        report = grade.format_report(scores, GOLD_FILE)
        self.assertIn("relationship api -> orders-db", report)
        self.assertIn("Redis cache", report)
        self.assertIn("x.py:9", report)
        self.assertIn("0.50", report)

    def test_the_cli_exits_zero_on_bad_scores(self):
        """It reports; it never gates."""
        poor = json.dumps({"system": {"name": "X"}, "containers": [{"id": "a", "name": "Redis"}]})
        with tempfile.TemporaryDirectory() as tmp:
            output = analyzed(tmp, poor)
            argv = sys.argv
            sys.argv = ["grade.py", "--output", str(output), "--repo", str(BOOKSHOP)]
            buffer = io.StringIO()
            try:
                with contextlib.redirect_stdout(buffer):
                    grade.main()
            finally:
                sys.argv = argv
        self.assertIn("recall", buffer.getvalue())

    def test_the_cli_json_flag_emits_parseable_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = analyzed(tmp, (BOOKSHOP / "c4-model.json").read_text(encoding="utf-8"))
            argv = sys.argv
            sys.argv = ["grade.py", "--output", str(output), "--repo", str(BOOKSHOP), "--json"]
            buffer = io.StringIO()
            try:
                with contextlib.redirect_stdout(buffer):
                    grade.main()
            finally:
                sys.argv = argv
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["recall"]["score"], 1.0)
        self.assertTrue(payload["render"]["ok"])

    def test_a_wrong_type_section_scores_zero_instead_of_crashing(self):
        """Agent JSON can put any type in a section; the grader must still report."""
        cases = [
            ("relationships", {"relationships": 5}, "relationships"),
            ("relationships as a string", {"relationships": "none"}, "relationships"),
            ("flows", {"flows": 5}, "flow_steps"),
            ("flow steps", {"flows": [{"steps": 5}]}, "flow_steps"),
            ("flow steps as a string", {"flows": [{"steps": "abc"}]}, "flow_steps"),
            ("containers", {"containers": 5}, "elements"),
            ("containers as a string", {"containers": "api"}, "elements"),
        ]
        for label, patch, part in cases:
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                output = analyzed(tmp, json.dumps({"system": {"name": "X"}, **patch}))
                scores = grade.grade(output, self.gold, BOOKSHOP)
                self.assertEqual(scores["recall"]["parts"][part][0], 0)
                self.assertIn("missed", scores["recall"])
                grade.format_report(scores, GOLD_FILE)

    def test_the_report_says_na_when_there_is_no_evidence(self):
        scores = {
            "recall": {"score": 0.0, "hits": 0, "total": 1,
                       "parts": {"elements": (0, 1), "relationships": (0, 0), "flow_steps": (0, 0)},
                       "missed": []},
            "hallucination": {"count": 0, "problems": []},
            "evidence": {"score": 1.0, "valid": 0, "total": 0, "problems": []},
            "render": {"ok": True, "status": "ok", "problems": [], "drift": []},
        }
        report = grade.format_report(scores, GOLD_FILE)
        self.assertIn("n/a (no evidence entries)", report)
        self.assertNotIn("1.00", report)

    def _run_cli(self, output):
        return subprocess.run(
            [sys.executable, str(EVALS / "grade.py"), "--output", str(output), "--repo", str(BOOKSHOP)],
            capture_output=True, text=True,
        )

    def test_the_process_exits_zero_on_terrible_scores(self):
        """Pins "reports, never gates" through a real exit code."""
        terrible = json.dumps({"system": {"name": "X"}, "containers": [{"id": "a", "name": "Redis cache"}]})
        with tempfile.TemporaryDirectory() as tmp:
            output = analyzed(tmp, terrible)
            result = self._run_cli(output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("recall", result.stdout)
        self.assertIn("0.00", result.stdout)

    def test_the_process_exits_one_when_there_is_no_model(self):
        """The other half: non-zero only when it cannot do its job."""
        with tempfile.TemporaryDirectory() as tmp:
            output = analyzed(tmp)
            (output / "c4-model.json").unlink(missing_ok=True)
            result = self._run_cli(output)
        self.assertEqual(result.returncode, 1)
        self.assertIn("no c4-model.json", result.stderr)


PROMPTS = EVALS / "triggers" / "prompts.jsonl"


class TestPrompts(unittest.TestCase):
    def setUp(self):
        self.cases = [json.loads(line) for line
                      in PROMPTS.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_there_are_at_least_twenty_cases(self):
        self.assertGreaterEqual(len(self.cases), 20)

    def test_every_case_has_the_four_keys(self):
        for case in self.cases:
            self.assertEqual(set(case), {"id", "prompt", "should_fire", "why"}, case)

    def test_ids_are_unique(self):
        ids = [case["id"] for case in self.cases]
        self.assertEqual(len(ids), len(set(ids)))

    def test_both_labels_are_well_represented(self):
        positive = [case for case in self.cases if case["should_fire"]]
        negative = [case for case in self.cases if not case["should_fire"]]
        self.assertGreaterEqual(len(positive), 10)
        self.assertGreaterEqual(len(negative), 8)

    def test_should_fire_is_a_boolean(self):
        for case in self.cases:
            self.assertIsInstance(case["should_fire"], bool, case)

    def test_every_prompt_is_a_real_sentence(self):
        for case in self.cases:
            self.assertIsInstance(case["prompt"], str, case)
            self.assertGreaterEqual(len(case["prompt"].strip()), 15, case)

    def test_every_case_explains_its_label(self):
        for case in self.cases:
            self.assertGreaterEqual(len(case["why"]), 15, case)


from unittest import mock  # noqa: E402

TRIGGERS = EVALS / "triggers"
if str(TRIGGERS) not in sys.path:
    sys.path.insert(0, str(TRIGGERS))

import run_triggers  # noqa: E402


class TestTriggerRunner(unittest.TestCase):
    def test_dry_run_prints_a_line_per_case_and_spawns_nothing(self):
        argv = sys.argv
        sys.argv = ["run_triggers.py", "--dry-run"]
        buffer = io.StringIO()
        try:
            with mock.patch.object(run_triggers.subprocess, "run") as spawn:
                with contextlib.redirect_stdout(buffer):
                    run_triggers.main()
        finally:
            sys.argv = argv
        spawn.assert_not_called()
        output = buffer.getvalue()
        for case in run_triggers.load_cases(PROMPTS):
            self.assertIn(case["id"], output)

    def test_the_command_runs_claude_headless_with_stream_json(self):
        command = run_triggers.command_for({"id": "t01", "prompt": "Draw the C4 diagram"})
        self.assertEqual(command[0], "claude")
        self.assertIn("-p", command)
        self.assertIn("Draw the C4 diagram", command)
        self.assertIn("stream-json", command)

    def test_bash_is_disallowed_so_the_analyzer_never_runs(self):
        command = run_triggers.command_for({"id": "t01", "prompt": "x"})
        self.assertIn("--disallowedTools", command)
        self.assertIn("Bash", command[command.index("--disallowedTools") + 1])

    def test_fired_detects_the_skill_by_name(self):
        events = '{"type":"assistant","message":{"content":[{"type":"tool_use",' \
                 '"name":"Skill","input":{"skill":"c4-diagrams"}}]}}'
        self.assertTrue(run_triggers.fired(events))

    def test_fired_is_false_when_the_skill_is_absent(self):
        events = '{"type":"assistant","message":{"content":[{"type":"text","text":"Sure."}]}}'
        self.assertFalse(run_triggers.fired(events))

    def test_fired_ignores_another_skill(self):
        events = '{"type":"assistant","message":{"content":[{"type":"tool_use",' \
                 '"name":"Skill","input":{"skill":"some-other-skill"}}]}}'
        self.assertFalse(run_triggers.fired(events))

    def test_fired_is_false_on_the_system_init_event(self):
        """The init event lists every tool and skill; it is not evidence of firing."""
        init = json.dumps({
            "type": "system", "subtype": "init",
            "tools": ["Bash", "Read", "Skill"],
            "skills": ["architecture-skills:c4-diagrams", "simplify"],
        })
        self.assertFalse(run_triggers.fired(init))

    def test_fired_detects_the_plugin_qualified_skill(self):
        event = json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Skill", "input": {"skill": "architecture-skills:c4-diagrams"}}]}})
        self.assertTrue(run_triggers.fired(event))

    def test_fired_ignores_unparseable_lines(self):
        event = json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Skill", "input": {"skill": "c4-diagrams"}}]}})
        self.assertTrue(run_triggers.fired("not json at all\n" + event))
        self.assertFalse(run_triggers.fired("not json at all\n{broken"))

    def test_score_computes_precision_and_recall(self):
        results = [
            {"id": "a", "should_fire": True,  "fired": True,  "status": "ok"},
            {"id": "b", "should_fire": True,  "fired": False, "status": "ok"},
            {"id": "c", "should_fire": False, "fired": True,  "status": "ok"},
            {"id": "d", "should_fire": False, "fired": False, "status": "ok"},
        ]
        summary = run_triggers.score(results)
        self.assertEqual(summary["true_positive"], 1)
        self.assertEqual(summary["false_negative"], 1)
        self.assertEqual(summary["false_positive"], 1)
        self.assertEqual(summary["true_negative"], 1)
        self.assertEqual(summary["precision"], 0.5)
        self.assertEqual(summary["recall"], 0.5)
        self.assertEqual(summary["errors"], 0)

    def test_an_errored_case_is_excluded_from_precision_and_recall(self):
        """An infrastructure failure is not evidence about the description."""
        results = [
            {"id": "a", "should_fire": True, "fired": True, "status": "ok"},
            {"id": "b", "should_fire": True, "fired": False, "status": "error"},
        ]
        summary = run_triggers.score(results)
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(summary["recall"], 1.0)
        self.assertEqual(summary["scored"], 1)


if __name__ == "__main__":
    unittest.main()
