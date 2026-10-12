"""
The `freight` eval fixture and its gold.

`bookshop` cannot measure the quality of the model an agent writes: the skill
tells the agent to follow `assets/c4-model-reference.md`, which is a copy of
bookshop's own `c4-model.json`, so the answer ships inside the instructions
(see evals/README.md). `freight` exists to be graded blind, and is built so
that an answer which only mirrors `c4-facts.json` scores badly.

Two things have to stay true or the gold stops measuring what it claims to:

1. the fixture's **traps** must still have the shape the gold assumes — a
   detector improvement could hand the agent an answer the gold expects it to
   work for, and the score would rise without the skill getting better;
2. the gold must still **separate** a careless answer from a careful one.

Both are asserted here rather than left to a human reading a score.
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

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "repos" / "freight"
GOLD_FILE = EVALS / "gold" / "freight.json"

# What an agent produces when it stops at the facts: every detected container
# drawn, including the dev-only console; no person, no external system, no
# flow. It is the answer the fixture exists to mark down.
CARELESS_MODEL = {
    "system": {"name": "Freight", "description": "Parcel tracking"},
    "containers": [
        {"id": "freight-api", "name": "freight-api", "description": "The tracking API",
         "evidence": ["api/pyproject.toml:1"]},
        {"id": "freight-worker", "name": "freight-worker", "description": "The poller",
         "evidence": ["worker/package.json:1"]},
        {"id": "adminer", "name": "adminer", "description": "Database console",
         "evidence": ["docker-compose.yml:29"]},
        {"id": "db-postgresql", "name": "PostgreSQL", "type": "database", "description": "Shipments",
         "evidence": ["docker-compose.yml:2"]},
        {"id": "db-redis", "name": "Redis", "type": "database", "description": "Cache",
         "evidence": ["api/freight/storage/cache.py:4"]},
    ],
    "relationships": [
        {"from": "freight-api", "to": "db-postgresql", "description": "Depends on"},
        {"from": "freight-worker", "to": "db-postgresql", "description": "Depends on"},
        {"from": "adminer", "to": "db-postgresql", "description": "Depends on"},
    ],
}


class FreightGoldTest(unittest.TestCase):
    def test_the_gold_is_well_formed(self):
        gold = grade.load_gold(GOLD_FILE)
        self.assertEqual(gold["repo"], "tests/fixtures/repos/freight")
        self.assertTrue((REPO_ROOT / gold["repo"]).is_dir())

    def test_the_fixture_ships_no_answer_of_its_own(self):
        # bookshop's c4-model.json is its reason to exist; freight must not
        # have one, or a run on it could read the answer off the disk.
        self.assertFalse((FIXTURE / "c4-model.json").exists())


class FreightTrapsTest(unittest.TestCase):
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

    def test_the_carrier_network_is_invisible_to_the_detectors(self):
        # Called through shared/src/http.ts with the URL in CARRIER_API_URL, so
        # no file that names a host also imports an HTTP client. Recall of the
        # `carrier` role therefore measures reading the code, not the facts.
        self.assertEqual(self.facts["external_systems"], [])
        variables = {v["name"]: v for v in self.facts["configuration"]["variables"]}
        self.assertIn("CARRIER_API_URL", variables)
        self.assertEqual(variables["CARRIER_API_URL"]["default"], "https://api.carrier.example/v3")

    def test_the_dev_only_console_is_detected_as_a_container(self):
        # It must reach the model author as a container fact: the judgement
        # being measured is putting it in `excluded`, not noticing it exists.
        self.assertIn("adminer", [c["id"] for c in self.facts["containers"]])

    def test_the_shared_library_is_a_component_not_a_container(self):
        ids = [c["id"] for c in self.facts["containers"]]
        self.assertNotIn("@freight/shared", ids)
        worker = next(c for c in self.facts["containers"] if c["id"] == "freight-worker")
        self.assertIn("@freight/shared", worker["components"]["nodes"])

    def test_the_status_cache_is_only_reachable_through_wrappers(self):
        redis = next(d for d in self.facts["data_stores"] if d["id"] == "db-redis")
        self.assertEqual(sorted(redis["used_by"]), ["freight-api", "freight-worker"])
        # Neither container touches redis directly: the API goes through
        # freight.storage, the poller through the shared library.
        self.assertEqual(redis["used_by_components"]["freight-api"], ["freight.storage"])
        self.assertEqual(redis["used_by_components"]["freight-worker"], ["@freight/shared"])
        # And it is not a compose service, so it cannot be read off the deployment.
        self.assertNotIn("redis", [s["name"] for s in self.facts["deployment"]["compose"]])


class FreightDiscriminationTest(unittest.TestCase):
    """The gold has to mark a careless answer down. On bookshop it cannot."""

    def test_an_answer_that_only_mirrors_the_facts_scores_badly(self):
        gold = grade.load_gold(GOLD_FILE)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            output.mkdir()
            run_analyzer(FIXTURE, output)
            (output / "c4-model.json").write_text(json.dumps(CARELESS_MODEL), encoding="utf-8")
            scores = grade.grade(output, gold, FIXTURE)

        self.assertLessEqual(scores["recall"]["score"], 0.5,
                             f"the gold stopped discriminating: {scores['recall']}")
        self.assertGreaterEqual(scores["hallucination"]["count"], 1,
                                "drawing the dev-only console must cost a hallucination")
        self.assertIn("forbidden 'adminer': adminer", scores["hallucination"]["problems"])
        missed = scores["recall"]["missed"]
        for item in ("element dispatcher", "element carrier", "relationship poller -> carrier"):
            self.assertIn(item, missed)


if __name__ == "__main__":
    unittest.main()
