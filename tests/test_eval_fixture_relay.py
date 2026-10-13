"""
The `relay` eval fixture and its gold.

`freight` measures, but it has no headroom: three blind authoring runs cleared
every trap and scored recall 1.00, so a change to the prompt reads 1.00 → 1.00
and proves nothing (BACKLOG B-29). `relay` is the harder fixture that row asks
for, built around the three shapes it names:

1. **a container reached only through a message queue** — the notifier consumes
   `delivery.routed`, which the router publishes. There is no call between
   them, no `depends_on` between them, and nothing in the facts relates them;
2. **a second system owning a store the first one writes** — the ledger belongs
   to the finance platform. Relay only appends to it, through one wrapper, and
   the detector folds it into the same `db-postgresql` fact as the routes
   database, so telling the two apart is reading, not detection;
3. **a flow crossing three containers** — courier → intake → bus → router →
   bus → notifier → SMS provider.

As for freight, the traps are asserted here rather than left to a human reading
a score: a detector improvement that hands the agent one of these answers would
raise the score without the skill getting better, and this file fails instead.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT, run_analyzer

EVALS = REPO_ROOT / "evals"
if str(EVALS) not in sys.path:
    sys.path.insert(0, str(EVALS))

import grade  # noqa: E402  (sys.path is set above)

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "repos" / "relay"
GOLD_FILE = EVALS / "gold" / "relay.json"

# What an agent produces when it stops at the facts: every detected container
# drawn, including the dev-only inbox; one database because the detector found
# one; no person, no external system, no flow.
CARELESS_MODEL = {
    "system": {"name": "Relay", "description": "Delivery scans"},
    "containers": [
        {"id": "intake", "name": "intake", "description": "The intake API",
         "evidence": ["intake/go.mod:1"]},
        {"id": "router", "name": "router", "description": "The router",
         "evidence": ["router/pyproject.toml:1"]},
        {"id": "relay-notifier", "name": "@relay/notifier", "description": "The notifier",
         "evidence": ["notifier/package.json:1"]},
        {"id": "mailpit", "name": "mailpit", "description": "Mail inbox",
         "evidence": ["docker-compose.yml:42"]},
        {"id": "db-postgresql", "name": "PostgreSQL", "type": "database", "description": "Database",
         "evidence": ["docker-compose.yml:7"]},
        {"id": "db-rabbitmq", "name": "RabbitMQ", "type": "queue", "description": "Message bus",
         "evidence": ["docker-compose.yml:2"]},
    ],
    "relationships": [
        {"from": "intake", "to": "db-rabbitmq", "description": "Depends on"},
        {"from": "router", "to": "db-rabbitmq", "description": "Depends on"},
        {"from": "router", "to": "db-postgresql", "description": "Depends on"},
        {"from": "relay-notifier", "to": "db-rabbitmq", "description": "Depends on"},
    ],
}


class RelayGoldTest(unittest.TestCase):
    def test_the_gold_is_well_formed(self):
        gold = grade.load_gold(GOLD_FILE)
        self.assertEqual(gold["repo"], "tests/fixtures/repos/relay")
        self.assertTrue((REPO_ROOT / gold["repo"]).is_dir())

    def test_the_fixture_ships_no_answer_of_its_own(self):
        self.assertFalse((FIXTURE / "c4-model.json").exists())

    def test_the_gold_asks_for_a_flow_across_three_containers(self):
        gold = grade.load_gold(GOLD_FILE)
        containers = {"intake", "router", "notifier"}
        in_steps = {end for step in gold["required_flow_steps"] for end in step}
        self.assertTrue(containers <= in_steps, in_steps)


class RelayTrapsTest(unittest.TestCase):
    """The detector gaps the gold is written against."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.facts, cls.summary = run_analyzer(FIXTURE, cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_the_analysis_itself_is_clean(self):
        # A degraded run would make a low score ambiguous: bad model, or bad input?
        self.assertEqual(self.summary["status"], "ok", self.summary["warnings"])

    def test_nothing_relates_the_router_to_the_notifier(self):
        # Trap 1. They share a topic name and nothing else, so an answer that
        # copies the facts cannot show the second half of the system's path.
        pairs = {(r["from"], r["to"]) for r in self.facts["relationships"]}
        self.assertNotIn(("router", "relay-notifier"), pairs)
        self.assertNotIn(("relay-notifier", "router"), pairs)
        both = {"intake", "router", "relay-notifier"}
        self.assertTrue(both <= {r["from"] for r in self.facts["relationships"]})
        self.assertEqual({r["to"] for r in self.facts["relationships"]} & both, set())

    def test_the_two_databases_are_one_fact(self):
        # Trap 2. The routes database and the finance platform's ledger are
        # both PostgreSQL, so the detector reports a single store. Splitting
        # them is reading README.md and router/ledger.py, not detection.
        stores = [d["id"] for d in self.facts["data_stores"]]
        self.assertEqual(sorted(stores), ["db-postgresql", "db-rabbitmq"])
        postgres = next(d for d in self.facts["data_stores"] if d["id"] == "db-postgresql")
        evidence = " ".join(postgres["evidence"])
        self.assertIn("ledger.py", evidence)
        self.assertIn("routes.py", evidence)

    def test_the_finance_platform_and_the_sms_provider_are_invisible(self):
        # Neither is in the facts: finance is named only in README.md and in a
        # connection string, and the SMS provider is called through undici,
        # which is not on the HTTP-client list. Recall of those two roles
        # therefore measures reading the code.
        self.assertEqual(self.facts["external_systems"], [])
        variables = {v["name"]: v for v in self.facts["configuration"]["variables"]}
        self.assertIn("SMS_API_URL", variables)
        self.assertEqual(variables["SMS_API_URL"]["default"], "https://api.sms-gate.example/v2/messages")

    def test_the_dev_only_inbox_is_detected_as_a_container(self):
        # It must reach the model author as a container fact: the judgement
        # being measured is putting it in `excluded`, not noticing it exists.
        self.assertIn("mailpit", [c["id"] for c in self.facts["containers"]])

    def test_the_contracts_package_is_not_a_container(self):
        self.assertNotIn("@relay/contracts", [c["id"] for c in self.facts["containers"]])


class RelayDiscriminationTest(unittest.TestCase):
    """The gold has to mark a careless answer down, and harder than freight does."""

    def test_an_answer_that_only_mirrors_the_facts_scores_badly(self):
        gold = grade.load_gold(GOLD_FILE)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            output.mkdir()
            run_analyzer(FIXTURE, output)
            (output / "c4-model.json").write_text(json.dumps(CARELESS_MODEL), encoding="utf-8")
            scores = grade.grade(output, gold, FIXTURE)

        self.assertLessEqual(scores["recall"]["score"], 0.35,
                             f"the gold stopped discriminating: {scores['recall']}")
        self.assertGreaterEqual(scores["hallucination"]["count"], 1,
                                "drawing the dev-only inbox must cost a hallucination")
        self.assertIn("forbidden 'mailpit': mailpit", scores["hallucination"]["problems"])
        missed = scores["recall"]["missed"]
        for item in ("element courier", "element ledger-db", "element finance", "element sms",
                     "relationship finance -> ledger-db", "relationship notifier -> sms"):
            self.assertIn(item, missed)


if __name__ == "__main__":
    unittest.main()
