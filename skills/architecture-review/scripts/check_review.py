"""Check an ArchitectureReview.md before it goes to the user.

The review is written by the agent, so nothing stops a wrong line number, a
finding with no scenario, or a lens that never mentions a finding. This script
is the feedback loop for that, the way `render_c4.py` is for the C4 model: it
lists every problem, the agent fixes them, and it runs again until it prints
`Review check: ok`.

Nine measures: the required sections are present and in order; every finding
has all seven fields with real content; every piece of evidence resolves to a
real line (or range) or a real signal id; findings are ranked High first; each
lens has an analysis that cites every finding; no scenario merely restates the
signal it came from; every signal is either cited or explained; the action plan
covers every finding; and the report says what it did not inspect. It checks
shape and groundedness, never correctness.

    python3 check_review.py <ArchitectureReview.md> <repository> [--evidence review-evidence.json]
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

# Allow running as a plain script from any directory, not only
# `python -m scripts.check_review` from the skill folder.
SKILL_DIR = Path(__file__).resolve().parent.parent
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from scripts.cli_support import UserError, require_python, run_cli

# Must run before the imports below: they use 3.10+ syntax.
require_python()

from scripts.repo_scan import SKIP_DIRS

SECTIONS = [
    "Executive summary",
    "Goals and quality attributes",
    "Scope and inputs",
    "Overall architecture",
    "Analysis by lens",
    "Key findings and action items",
    "Action plan",
    "What I inspected and what I did not",
]
LENSES = ["Security", "Data", "Application", "Infrastructure"]
FIELDS = ["Priority", "Lens", "Evidence", "Scenario", "Fix", "Tradeoff", "Confidence"]
RANK = {"High": 0, "Medium": 1, "Low": 2}
MIN_WORDS = {"Scenario": 12, "Fix": 8, "Tradeoff": 2}
MIN_REASON_WORDS = {"Priority": 4, "Confidence": 3}
MIN_LENS_WORDS = 15
MIN_INSPECTED_WORDS = 25
RESTATED_COVERAGE = 0.8  # share of the signal's words a restating scenario contains
MIN_NEW_WORDS = 10  # words a scenario must add beyond the signal's own

H2 = re.compile(r"(?m)^## (.+?)\s*$")
H3 = re.compile(r"(?m)^### (.+?)\s*$")
FINDING_HEAD = re.compile(r"(?m)^### F(\d+): (.+?)\s*$")
FIELD_LINE = re.compile(r"^- \*\*(\w+):\*\*\s*(.*)$")
PRIORITY = re.compile(r"^(High|Medium|Low)\s+[—–-]\s+(.+)$")
CONFIDENCE = re.compile(r"^(High|Medium|Low)(?:[-/](?:High|Medium|Low))?\b[\s—–:-]*(.*)$", re.S)
LOCATION = re.compile(r"^([^\s:`]*):(\d+)(?:-(\d+))?$")
BARE_PATH = re.compile(r"^[\w.\-]+(?:/[\w.\-]+)*$")
SIGNAL_ID = re.compile(r"^(sec|dat|app|inf)-\d+$")
FINDING_ID = re.compile(r"\bF(\d+)\b")

MEASURES = ["sections", "finding_fields", "evidence_resolves", "ranked", "lens_analysis",
            "not_restating", "signals_accounted", "action_plan", "inspected"]


def words(text):
    return re.findall(r"[A-Za-z0-9_']+", text.lower())


def sections(text):
    """{H2 title: body}, in document order."""
    matches = list(H2.finditer(text))
    return {
        m.group(1): text[m.end(): matches[i + 1].start() if i + 1 < len(matches) else len(text)]
        for i, m in enumerate(matches)
    }


def parse_findings(body):
    """[(number, title, {field: text})] from the Key findings section."""
    heads = list(FINDING_HEAD.finditer(body))
    findings = []
    for i, head in enumerate(heads):
        block = body[head.end(): heads[i + 1].start() if i + 1 < len(heads) else len(body)]
        fields, current = {}, None
        for line in block.splitlines():
            m = FIELD_LINE.match(line)
            if m:
                current = m.group(1)
                fields[current] = m.group(2).strip()
            elif current and line.startswith("  ") and line.strip():
                fields[current] += " " + line.strip()
            elif line.strip():
                current = None
        findings.append((int(head.group(1)), head.group(2), fields))
    return findings


def evidence_tokens(fields):
    return re.findall(r"`([^`]+)`", fields.get("Evidence", ""))


def check_sections(found):
    problems = [f"missing section: {s}" for s in SECTIONS if s not in found]
    present = [t for t in found if t in SECTIONS]
    if not problems and present != SECTIONS:
        problems.append("sections are out of order")
    return problems


def check_fields(findings):
    if not findings:
        return ["no findings (### F1: ...) in the Key findings section"]
    problems = []
    for number, _title, fields in findings:
        for name in FIELDS:
            if not fields.get(name):
                problems.append(f"F{number}: {name} is missing or empty")
        for name, minimum in MIN_WORDS.items():
            if fields.get(name) and len(words(fields[name])) < minimum:
                problems.append(f"F{number}: {name} is under {minimum} words")
        priority = fields.get("Priority", "")
        m = PRIORITY.match(priority)
        if priority and not m:
            problems.append(f"F{number}: Priority must be 'High|Medium|Low — reason'")
        elif m and len(words(m.group(2))) < MIN_REASON_WORDS["Priority"]:
            problems.append(f"F{number}: Priority has no stated reason")
        confidence = fields.get("Confidence", "")
        m = CONFIDENCE.match(confidence)
        if confidence and not m:
            problems.append(f"F{number}: Confidence must start with High, Medium or Low, then its basis")
        elif m and len(words(m.group(2))) < MIN_REASON_WORDS["Confidence"]:
            problems.append(f"F{number}: Confidence has no stated basis")
        if fields.get("Lens") and fields["Lens"] not in LENSES:
            problems.append(f"F{number}: Lens must be one of {', '.join(LENSES)}")
    return problems


class Repository:
    """Resolves the paths a review cites, and finds a unique match for a bare file name."""

    def __init__(self, root):
        self.root = Path(root)
        self._by_name = None

    def file(self, rel):
        path = self.root / rel
        return path if path.is_file() else None

    def matches_for(self, name):
        if self._by_name is None:
            self._by_name = {}
            for folder, dirs, files in os.walk(self.root):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for f in files:
                    self._by_name.setdefault(f, []).append(
                        (Path(folder) / f).relative_to(self.root).as_posix())
        return self._by_name.get(name, [])


def check_location(token, previous, repo):
    """(problem or None, path to remember) for one backticked evidence token."""
    m = LOCATION.match(token)
    if not m:
        if BARE_PATH.match(token) and ("/" in token or "." in token):
            if repo.file(token):
                return None, token
            return f"{token}: file not found", previous
        return f"{token}: not a location; put prose outside the backticks", previous
    rel = m.group(1) or previous
    if not rel:
        return f"{token}: no file named before it; write the full repo-relative path", previous
    path = repo.file(rel)
    if path is None:
        found = repo.matches_for(Path(rel).name) if "/" not in rel else []
        if len(found) == 1:
            # Carry the intended path forward so a following ':N' shorthand is judged against it.
            return f"{token}: file not found; use the full repo-relative path: {found[0]}", found[0]
        return f"{token}: file not found", previous
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    lo, hi = int(m.group(2)), int(m.group(3) or m.group(2))
    if lo < 1 or hi < lo:
        return f"{token}: not a valid line range", rel
    if hi > len(lines):
        return f"{token}: line {hi} is past the end of {rel} ({len(lines)} lines)", rel
    if not any(line.strip() for line in lines[lo - 1:hi]):
        return f"{token}: cites only blank lines in {rel}", rel
    return None, rel


def check_evidence(findings, repo, signal_ids):
    problems = []
    for number, _title, fields in findings:
        tokens = evidence_tokens(fields)
        if not tokens:
            problems.append(f"F{number}: no backticked evidence")
        previous, resolved = None, 0
        for token in tokens:
            if SIGNAL_ID.match(token):
                if signal_ids is not None and token not in signal_ids:
                    problems.append(f"F{number}: {token}: no such signal")
                else:
                    resolved += 1
                continue
            problem, previous = check_location(token, previous, repo)
            if problem:
                problems.append(f"F{number}: {problem}")
            else:
                resolved += 1
        if tokens and not resolved:
            problems.append(f"F{number}: none of its evidence resolves")
    return problems


def check_ranked(findings):
    numbers = [n for n, _t, _f in findings]
    problems = []
    if numbers != list(range(1, len(numbers) + 1)):
        problems.append(f"finding numbers must run F1..F{len(numbers)} in order, got {numbers}")
    ranks = []
    for number, _t, fields in findings:
        m = PRIORITY.match(fields.get("Priority", ""))
        if m:
            ranks.append((number, RANK[m.group(1)]))
    for (_a, rank_a), (b, rank_b) in zip(ranks, ranks[1:]):
        if rank_b < rank_a:
            problems.append(f"F{b} outranks the finding before it; order findings High first")
            break
    return problems


def check_lens_analysis(found, findings):
    body = found.get("Analysis by lens", "")
    parts = {}
    heads = list(H3.finditer(body))
    for i, head in enumerate(heads):
        parts[head.group(1)] = body[head.end(): heads[i + 1].start() if i + 1 < len(heads) else len(body)]
    problems = []
    for lens in LENSES:
        if lens not in parts:
            problems.append(f"no '### {lens}' analysis")
        elif len(words(parts[lens])) < MIN_LENS_WORDS:
            problems.append(f"{lens} analysis is under {MIN_LENS_WORDS} words")
    cited = {int(n) for n in FINDING_ID.findall(body)}
    for number, _t, _f in findings:
        if number not in cited:
            problems.append(f"F{number} is not cited in the lens analysis")
    return problems


def check_not_restating(findings, signals):
    problems = []
    for number, title, fields in findings:
        scenario = set(words(fields.get("Scenario", "")))
        if not scenario:
            continue
        if scenario == set(words(title)):
            problems.append(f"F{number}: Scenario repeats the title")
        for token in evidence_tokens(fields):
            summary = signals.get(token)
            if summary:
                theirs = set(words(summary))
                covered = len(scenario & theirs) / len(theirs)
                added = len(scenario - theirs)
                if covered >= RESTATED_COVERAGE and added < MIN_NEW_WORDS:
                    problems.append(f"F{number}: Scenario restates signal {token}: it repeats {covered:.0%} of "
                                    f"its words and adds only {added}")
    return problems


def check_signals_accounted(report, signal_ids):
    """Every signal in the evidence file appears in the review: in a finding, or in the closing section."""
    problems = []
    for signal_id in sorted(signal_ids):
        if not re.search(rf"\b{re.escape(signal_id)}\b", report):
            problems.append(f"signal {signal_id} is not mentioned: cite it in a finding, or say in the last "
                            "section why you set it aside")
    return problems


def check_action_plan(found, findings):
    body = found.get("Action plan", "")
    rows = [line for line in body.splitlines() if line.startswith("|") and not re.match(r"^\|[\s\-|]+$", line)]
    problems = []
    if len(rows) < 2:
        problems.append("the action plan has no rows")
    cited = {int(n) for n in FINDING_ID.findall("\n".join(rows[1:]))}
    known = {n for n, _t, _f in findings}
    for number in sorted(known - cited):
        problems.append(f"F{number} is not in the action plan")
    for number in sorted(cited - known):
        problems.append(f"the action plan cites F{number}, which does not exist")
    return problems


def check_inspected(found):
    body = found.get("What I inspected and what I did not", "")
    if len(words(body)) < MIN_INSPECTED_WORDS:
        return [f"the inspected/not-inspected section is under {MIN_INSPECTED_WORDS} words"]
    return []


def check_review(report, repo, evidence=None):
    """{measure: [problems]} for a review; an empty list means the measure passes."""
    found = sections(report)
    findings = parse_findings(found.get("Key findings and action items", ""))
    signals = {s["id"]: s["summary"] for s in (evidence or {}).get("signals", [])}
    return {
        "sections": check_sections(found),
        "finding_fields": check_fields(findings),
        "evidence_resolves": check_evidence(findings, Repository(repo), set(signals) if evidence else None),
        "ranked": check_ranked(findings),
        "lens_analysis": check_lens_analysis(found, findings),
        "not_restating": check_not_restating(findings, signals),
        "signals_accounted": check_signals_accounted(report, signals),
        "action_plan": check_action_plan(found, findings),
        "inspected": check_inspected(found),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check an ArchitectureReview.md: lists every problem to fix.")
    parser.add_argument("report", help="Path to ArchitectureReview.md")
    parser.add_argument("repository", help="The reviewed repository, to resolve file:line evidence")
    parser.add_argument("--evidence", help="review-evidence.json (default: the one beside the report, if any)")
    parser.add_argument("--debug", action="store_true", help="Print a traceback on an internal error")
    args = parser.parse_args(argv)

    def run():
        report = Path(args.report)
        if not report.is_file():
            raise UserError("review not found", path=str(report))
        if not Path(args.repository).is_dir():
            raise UserError("repository not found", path=str(args.repository))
        evidence_path = Path(args.evidence) if args.evidence else report.with_name("review-evidence.json")
        evidence = None
        if evidence_path.is_file():
            try:
                evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as ex:
                raise UserError(f"could not read the evidence: {ex}", path=str(evidence_path)) from ex
        elif args.evidence:
            raise UserError("evidence file not found", path=str(evidence_path))

        results = check_review(report.read_text(encoding="utf-8"), args.repository, evidence)
        total = 0
        for measure in MEASURES:
            for problem in results[measure]:
                print(f"PROBLEM: {measure}: {problem}")
                total += 1
        print("Review check: ok" if not total else f"Review check: {total} problem(s)")
        if total:
            sys.exit(1)

    run_cli(run, debug=args.debug)


if __name__ == "__main__":
    main()
