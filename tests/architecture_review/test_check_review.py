"""check_review accepts the reference review and rejects each way a review goes wrong."""
import contextlib
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import review_helpers as H
from scripts import check_review as C
from scripts import collect_evidence

SCRIPT = H.SKILL / "scripts" / "check_review.py"
EXAMPLE = (H.SKILL / "assets" / "example-review.md").read_text(encoding="utf-8")
EVIDENCE = collect_evidence.collect(H.FIXTURE_REPO, H.FIXTURE_FACTS)


def check(report):
    return C.check_review(report, H.FIXTURE_REPO, EVIDENCE)


def failed(report):
    return {measure for measure, problems in check(report).items() if problems}


def with_evidence(report, finding, evidence_line):
    """The report with one finding's Evidence line replaced."""
    start = report.index(f"### {finding}:")
    e_start = report.index("- **Evidence:**", start)
    e_end = report.index("\n", e_start)
    return report[:e_start] + f"- **Evidence:** {evidence_line}" + report[e_end:]


class ReferenceReviewTest(unittest.TestCase):
    def test_the_example_review_passes_every_measure(self):
        self.assertEqual(failed(EXAMPLE), set())

    def test_the_example_review_never_names_a_secret_value(self):
        self.assertNotIn("dev-secret-key", EXAMPLE)

    def test_every_signal_the_example_cites_exists_in_the_live_evidence(self):
        ids = {s["id"] for s in EVIDENCE["signals"]}
        body = C.sections(EXAMPLE)["Key findings and action items"]
        cited = {t for _n, _t, f in C.parse_findings(body) for t in C.evidence_tokens(f) if C.SIGNAL_ID.match(t)}
        self.assertTrue(cited <= ids, cited - ids)

    def test_the_example_accounts_for_every_signal(self):
        body = C.sections(EXAMPLE)["Key findings and action items"]
        cited = {t for _n, _t, f in C.parse_findings(body) for t in C.evidence_tokens(f)}
        self.assertEqual({s["id"] for s in EVIDENCE["signals"]} - cited, set())


class ShallowReviewTest(unittest.TestCase):
    def test_a_missing_section_fails(self):
        self.assertEqual(failed(EXAMPLE.replace("## Action plan", "## Plan")), {"sections", "action_plan"})

    def test_a_finding_with_no_scenario_fails(self):
        self.assertIn("finding_fields", failed(EXAMPLE.replace("- **Scenario:**", "- **Notes:**", 1)))

    def test_a_one_line_scenario_fails(self):
        start = EXAMPLE.index("- **Scenario:**")
        end = EXAMPLE.index("- **Fix:**", start)
        self.assertIn("finding_fields", failed(EXAMPLE[:start] + "- **Scenario:** It is bad.\n" + EXAMPLE[end:]))

    def test_a_priority_with_no_reason_fails(self):
        bad = EXAMPLE.replace("- **Priority:** High — the worker fails at import time, so no background "
                              "processing can happen as deployed", "- **Priority:** High", 1)
        self.assertIn("finding_fields", failed(bad))

    def test_findings_out_of_priority_order_fail(self):
        self.assertIn("ranked", failed(EXAMPLE.replace("**Priority:** Low — it needs", "**Priority:** High — it needs", 1)))

    def test_a_finding_missing_from_the_lens_analysis_fails(self):
        split = EXAMPLE.index("## Key findings and action items")
        self.assertEqual(failed(EXAMPLE[:split].replace("(F7)", "") + EXAMPLE[split:]), {"lens_analysis"})

    def test_a_finding_missing_from_the_action_plan_fails(self):
        bad = EXAMPLE.replace("| 6 | Run the worker as a non-root user | F7 | hours |\n", "")
        self.assertEqual(failed(bad), {"action_plan"})

    def test_a_scenario_that_restates_its_signal_fails(self):
        signal = next(s for s in EVIDENCE["signals"] if s["id"] == "sec-03")
        start = EXAMPLE.index("### F7")
        s_start = EXAMPLE.index("- **Scenario:**", start)
        s_end = EXAMPLE.index("- **Fix:**", s_start)
        bad = EXAMPLE[:s_start] + f"- **Scenario:** {signal['summary']}. This is a problem.\n" + EXAMPLE[s_end:]
        self.assertIn("not_restating", failed(bad))

    def test_an_empty_inspected_section_fails(self):
        i = EXAMPLE.index("## What I inspected")
        self.assertIn("inspected", failed(EXAMPLE[:i] + "## What I inspected and what I did not\n\nNothing.\n"))

    def test_a_signal_list_dressed_as_a_review_fails_broadly(self):
        report = "# Architecture Review\n\n## Headline findings\n\n- **[Major]** Dockerfile has no HEALTHCHECK\n"
        self.assertGreaterEqual(len(failed(report)), 4)


class SignalsAccountedTest(unittest.TestCase):
    def test_a_signal_nobody_mentions_is_a_problem(self):
        bad = EXAMPLE.replace("`sec-03`", "`worker/Dockerfile:1`")  # F7 no longer cites it, nothing else does
        problems = check(bad)["signals_accounted"]
        self.assertEqual(len(problems), 1)
        self.assertIn("sec-03", problems[0])

    def test_a_signal_explained_only_in_the_last_section_is_accounted_for(self):
        bad = EXAMPLE.replace(", `sec-03`", "")
        bad += "\nSignal sec-03 was a lead I confirmed by reading the Dockerfile, and F7 covers it.\n"
        self.assertEqual(check(bad)["signals_accounted"], [])

    def test_a_partial_id_does_not_count(self):
        bad = EXAMPLE.replace("`sec-03`", "`worker/Dockerfile:1`") + "\nsec-030 is unrelated.\n"
        self.assertEqual(len(check(bad)["signals_accounted"]), 1)

    def test_without_an_evidence_file_there_is_nothing_to_account_for(self):
        self.assertEqual(C.check_review(EXAMPLE, H.FIXTURE_REPO)["signals_accounted"], [])


class EvidenceTest(unittest.TestCase):
    """What a reader can follow is accepted; what points nowhere is not."""

    def problems(self, evidence_line, finding="F1"):
        return check(with_evidence(EXAMPLE, finding, evidence_line))["evidence_resolves"]

    def test_a_line_range_is_accepted(self):
        self.assertEqual(self.problems("`worker/tasks.py:2-3`"), [])

    def test_a_bare_existing_file_is_accepted(self):
        self.assertEqual(self.problems("`worker/Dockerfile`"), [])

    def test_a_shorthand_line_continues_the_previous_path(self):
        self.assertEqual(self.problems("`worker/tasks.py:2`, `:3`"), [])

    def test_a_shorthand_with_nothing_before_it_is_a_problem(self):
        self.assertEqual(len(self.problems("`:3`, `worker/tasks.py:2`")), 1)

    def test_a_range_past_the_end_of_the_file_is_caught(self):
        # the real blind-run mistake: a 102-line file cited at lines 152-158
        problems = self.problems("`worker/tasks.py:152-158`, `sec-01`")
        self.assertEqual(len(problems), 1)
        self.assertIn("past the end of worker/tasks.py (10 lines)", problems[0])

    def test_a_bare_basename_gets_the_full_path_as_a_hint(self):
        self.assertIn("worker/tasks.py", self.problems("`tasks.py:2`")[0])

    def test_a_shorthand_after_a_bare_basename_is_judged_against_the_intended_file(self):
        problems = self.problems("`tasks.py:2`, `:3`")
        self.assertEqual(len(problems), 1, problems)  # only the basename; ':3' follows worker/tasks.py

    def test_prose_or_config_in_backticks_is_a_problem(self):
        problems = self.problems("`worker/tasks.py:2`, `spring.data.redis.timeout: 2s`")
        self.assertEqual(len(problems), 1)
        self.assertIn("put prose outside the backticks", problems[0])

    def test_a_file_that_does_not_exist_is_a_problem(self):
        self.assertIn("file not found", self.problems("`worker/gone.py:2`, `sec-01`")[0])

    def test_a_citation_of_blank_lines_is_a_problem(self):
        self.assertIn("blank lines", self.problems("`worker/tasks.py:4`, `sec-01`")[0])

    def test_an_unknown_signal_is_a_problem(self):
        self.assertIn("no such signal", self.problems("`worker/tasks.py:2`, `sec-99`")[0])

    def test_a_finding_whose_evidence_all_fails_says_so(self):
        self.assertIn("none of its evidence resolves", " ".join(self.problems("`worker/gone.py:2`")))


class ConfidenceTest(unittest.TestCase):
    def problems(self, text):
        bad = re.sub(r"(?m)^- \*\*Confidence:\*\* .*$", f"- **Confidence:** {text}", EXAMPLE, count=1)
        return check(bad)["finding_fields"]

    def test_a_single_level_with_a_basis_passes(self):
        self.assertEqual(self.problems("Medium — the shared URL is certain but nothing reads the database yet"), [])

    def test_a_compound_level_passes(self):
        self.assertEqual(self.problems("Low-Medium — read from the code, not run"), [])

    def test_a_level_split_by_claim_passes(self):
        self.assertEqual(self.problems("High on the type mismatch, which I read on both lines. Medium on the effect."), [])

    def test_no_level_fails(self):
        self.assertTrue(self.problems("fairly sure, I read the code"))

    def test_a_level_with_no_basis_fails(self):
        self.assertIn("no stated basis", self.problems("High")[0])

    def test_a_two_word_tradeoff_passes(self):
        bad = re.sub(r"(?m)^- \*\*Tradeoff:\*\* .*$", "- **Tradeoff:** CI upkeep.", EXAMPLE, count=1)
        self.assertEqual(check(bad)["finding_fields"], [])


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        proc = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
        return proc.returncode, proc.stdout, proc.stderr

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        (self.folder / "review-evidence.json").write_text(json.dumps(EVIDENCE), encoding="utf-8")

    def write(self, text):
        path = self.folder / "ArchitectureReview.md"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_a_good_review_prints_ok_and_exits_0(self):
        code, out, _ = self.run_cli(self.write(EXAMPLE), str(H.FIXTURE_REPO))
        self.assertEqual((code, out.strip()), (0, "Review check: ok"))

    def test_problems_are_listed_one_per_line_and_exit_1(self):
        bad = with_evidence(EXAMPLE, "F2", "`worker/tasks.py:152-158`, `sec-99`")
        code, out, _ = self.run_cli(self.write(bad), str(H.FIXTURE_REPO))
        self.assertEqual(code, 1)
        lines = out.strip().splitlines()
        self.assertTrue(all(line.startswith("PROBLEM: ") for line in lines[:-1]), lines)
        self.assertEqual(lines[-1], "Review check: 3 problem(s)")

    def test_the_evidence_beside_the_report_is_found_without_a_flag(self):
        bad = with_evidence(EXAMPLE, "F2", "`worker/tasks.py:2`, `sec-99`")
        _, out, _ = self.run_cli(self.write(bad), str(H.FIXTURE_REPO))
        self.assertIn("no such signal", out)

    def test_a_missing_review_is_one_error_line(self):
        code, _, err = self.run_cli(str(self.folder / "nope.md"), str(H.FIXTURE_REPO))
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("ERROR: "), err)
        self.assertNotIn("Traceback", err)

    def test_a_missing_repository_is_one_error_line(self):
        code, _, err = self.run_cli(self.write(EXAMPLE), str(self.folder / "no-repo"))
        self.assertEqual(code, 1)
        self.assertIn("repository not found", err)

    def test_main_exits_1_when_there_are_problems(self):
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as raised:
            C.main([self.write("# nothing\n"), str(H.FIXTURE_REPO)])
        self.assertEqual(raised.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
