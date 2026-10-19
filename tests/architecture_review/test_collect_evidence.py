"""collect_evidence end to end: the fixture repository, the evidence file, the CLI."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import review_helpers as H
from scripts import collect_evidence
from scripts.cli_support import UserError

SCRIPT = H.SKILL / "scripts" / "collect_evidence.py"
EXPECTED_KINDS = {
    "credentials-in-url", "auth-markers-absent", "runs-as-root", "models-without-migrations",
    "shared-store", "cross-container-import", "no-healthcheck",
}


class FixtureEvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = collect_evidence.collect(H.FIXTURE_REPO, H.FIXTURE_FACTS)

    def test_the_fixtures_known_patterns_are_all_found_and_nothing_else(self):
        self.assertEqual({s["kind"] for s in self.evidence["signals"]}, EXPECTED_KINDS)

    def test_ids_are_unique_and_carry_the_lens_prefix(self):
        ids = [s["id"] for s in self.evidence["signals"]]
        self.assertEqual(len(ids), len(set(ids)))
        prefix = {"security": "sec", "data": "dat", "application": "app", "infrastructure": "inf"}
        for s in self.evidence["signals"]:
            self.assertTrue(s["id"].startswith(prefix[s["lens"]] + "-"), s)

    def test_every_location_points_at_a_real_line(self):
        for s in self.evidence["signals"]:
            self.assertTrue(s["locations"], s)
            for location in s["locations"]:
                rel, _, line = location.rpartition(":")
                lines = (H.FIXTURE_REPO / rel).read_text(encoding="utf-8").splitlines()
                self.assertTrue(1 <= int(line) <= len(lines), location)

    def test_no_secret_value_reaches_the_evidence(self):
        self.assertNotIn("dev-secret-key", json.dumps(self.evidence))

    def test_the_context_describes_the_system_and_its_documents(self):
        context = self.evidence["context"]
        self.assertEqual([c["id"] for c in context["containers"]], ["inventory-api", "inventory-worker"])
        self.assertEqual(context["compose_services"], ["api", "worker", "db"])
        self.assertEqual(context["documents"], ["README.md"])
        self.assertTrue(self.evidence["not_checked"])

    def test_two_runs_give_the_same_evidence(self):
        self.assertEqual(self.evidence, collect_evidence.collect(H.FIXTURE_REPO, H.FIXTURE_FACTS))


class ContextTest(unittest.TestCase):
    def make(self, files, model=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text, encoding="utf-8")
        facts = root / "docs-out" / "c4-facts.json"
        facts.parent.mkdir()
        facts.write_text(H.FIXTURE_FACTS.read_text(encoding="utf-8"), encoding="utf-8")
        if model is not None:
            facts.with_name("c4-model.json").write_text(model, encoding="utf-8")
        return collect_evidence.collect(root, facts)["context"]

    def test_ci_and_hosting_files_are_listed_by_the_collector_itself(self):
        context = self.make({"azure-pipelines.yml": "x", ".github/workflows/ci.yml": "x", "ecosystem.config.js": "x",
                             "Dockerfile": "FROM x:1\n", "src/a.ts": "x"})
        self.assertEqual(context["ci_files"], [".github/workflows/ci.yml", "azure-pipelines.yml"])
        self.assertEqual(context["hosting_files"], ["Dockerfile", "ecosystem.config.js"])

    def test_what_the_c4_model_adds_is_in_the_context(self):
        model = ('{"people": [{"id": "staff", "name": "Staff"}], "external_systems": [{"id": "ext-postmark", '
                 '"name": "Postmark", "description": "Sends email"}], "excluded": [{"id": "ext-x", "reason": "dead"}], '
                 '"flows": [{"id": "f", "name": "Contact form"}]}')
        context = self.make({"a.ts": "x"}, model)
        self.assertEqual([e["id"] for e in context["model"]["external_systems"]], ["ext-postmark"])
        self.assertEqual(context["model"]["excluded"], [{"id": "ext-x", "reason": "dead"}])
        self.assertEqual(context["model"]["flows"], ["Contact form"])

    def test_a_capped_document_list_says_how_many_there_are(self):
        files = {f"docs/plans/p{i:02d}.md": "x" for i in range(collect_evidence.MAX_DOCUMENTS + 4)}
        context = self.make(files)
        self.assertEqual(len(context["documents"]), collect_evidence.MAX_DOCUMENTS)
        self.assertEqual(context["documents_total"], collect_evidence.MAX_DOCUMENTS + 4)

    def test_the_endpoint_count_is_named_as_what_c4_detected(self):
        context = self.make({"a.ts": "x"})
        self.assertNotIn("endpoints", context)
        self.assertEqual(context["endpoints_detected"], 1)

    def test_no_model_is_none_and_a_broken_one_is_reported(self):
        self.assertIsNone(self.make({"a.ts": "x"})["model"])
        self.assertIn("error", self.make({"a.ts": "x"}, "{not json")["model"])


class DocumentsTest(unittest.TestCase):
    def test_shallow_documents_come_first_so_the_cap_drops_the_deep_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("x", encoding="utf-8")
            (root / "docs" / "plans").mkdir(parents=True)
            (root / "docs" / "architecture.md").write_text("x", encoding="utf-8")
            for i in range(collect_evidence.MAX_DOCUMENTS + 5):
                (root / "docs" / "plans" / f"plan-{i:02d}.md").write_text("x", encoding="utf-8")
            found = collect_evidence.find_documents(root)
        self.assertEqual(found[:2], ["README.md", "docs/architecture.md"])
        self.assertEqual(len(found), collect_evidence.MAX_DOCUMENTS + 7)  # every document; the context caps it


class InputErrorTest(unittest.TestCase):
    def test_missing_facts_say_to_run_c4_diagrams_first(self):
        with self.assertRaises(UserError) as raised:
            collect_evidence.collect(H.FIXTURE_REPO, H.FIXTURE_REPO / "no-such-facts.json")
        self.assertIn("c4-diagrams", str(raised.exception))

    def test_malformed_facts_are_a_user_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "c4-facts.json"
            bad.write_text("{not json", encoding="utf-8")
            with self.assertRaises(UserError):
                collect_evidence.collect(H.FIXTURE_REPO, bad)
            bad.write_text('{"repository": "x"}', encoding="utf-8")
            with self.assertRaises(UserError) as raised:
                collect_evidence.collect(H.FIXTURE_REPO, bad)
            self.assertIn("containers", str(raised.exception))

    def test_a_missing_repository_is_a_user_error(self):
        with self.assertRaises(UserError):
            collect_evidence.collect(H.FIXTURE_REPO / "nope", H.FIXTURE_FACTS)


class CliTest(unittest.TestCase):
    def run_cli(self, *args, cwd=None):
        proc = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=cwd,
                              env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        return proc.returncode, proc.stdout, proc.stderr

    def test_writes_review_evidence_json_and_reports_the_count(self):
        with tempfile.TemporaryDirectory() as out:
            code, stdout, _ = self.run_cli(str(H.FIXTURE_REPO), "--facts", str(H.FIXTURE_FACTS), "--output", out)
            self.assertEqual(code, 0)
            self.assertIn("Evidence: 7 signal(s)", stdout)
            written = json.loads((Path(out) / "review-evidence.json").read_text(encoding="utf-8"))
            self.assertEqual({s["kind"] for s in written["signals"]}, EXPECTED_KINDS)

    def test_defaults_to_the_c4_output_folder_for_the_repository(self):
        with tempfile.TemporaryDirectory() as cwd:
            docs = Path(cwd) / "architecture-docs" / H.FIXTURE_REPO.name
            docs.mkdir(parents=True)
            (docs / "c4-facts.json").write_text(H.FIXTURE_FACTS.read_text(encoding="utf-8"), encoding="utf-8")
            code, _, _ = self.run_cli(str(H.FIXTURE_REPO), cwd=cwd)
            self.assertEqual(code, 0)
            self.assertTrue((docs / "review-evidence.json").is_file())

    def test_missing_facts_exit_1_with_one_line(self):
        with tempfile.TemporaryDirectory() as cwd:
            code, _, stderr = self.run_cli(str(H.FIXTURE_REPO), cwd=cwd)
        self.assertEqual(code, 1)
        self.assertTrue(stderr.startswith("ERROR: "), stderr)
        self.assertIn("run the c4-diagrams skill", stderr)
        self.assertNotIn("Traceback", stderr)


if __name__ == "__main__":
    unittest.main()
