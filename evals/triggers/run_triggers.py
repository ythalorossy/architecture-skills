"""Measure whether the c4-diagrams skill fires on a labelled set of prompts.

`--dry-run` prints the plan and calls nothing; it is what CI exercises.
`--run` sends each prompt to a real headless Claude session and looks for a
Skill invocation naming c4-diagrams in the emitted events — what the host
actually did, not what a model says it would do.

Each case runs in an empty temporary working directory with Bash disallowed.
Firing stays observable (the Skill invocation is emitted before any script
runs) while the analyzer never executes against anything. Without this, one
positive run would analyze the current directory fifteen times over.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROMPTS = HERE / "prompts.jsonl"
SKILL_NAME = "c4-diagrams"
TIMEOUT_SECONDS = 180


def load_cases(path=PROMPTS):
    """The labelled prompts, in file order. Blank lines are ignored."""
    cases = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            cases.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"ERROR: {path}:{number}: not valid JSON: {exc}") from exc
    return cases


def command_for(case):
    """The exact headless Claude command for one case."""
    return [
        "claude",
        "-p", case["prompt"],
        "--output-format", "stream-json",
        "--verbose",
        "--disallowedTools", "Bash,Write,Edit",
    ]


def fired(events_text):
    """Did any emitted event invoke the c4-diagrams skill?

    Scanning the raw text rather than parsing every event shape keeps this
    working when the CLI's event schema shifts: the skill's name appearing
    beside a Skill tool use is the signal.
    """
    for line in events_text.splitlines():
        if SKILL_NAME not in line:
            continue
        if '"Skill"' in line or '"skill"' in line:
            return True
    return False


def run_case(case):
    """Run one case in an empty temp directory. Returns a result dict."""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            completed = subprocess.run(
                command_for(case), cwd=tmp, capture_output=True, text=True,
                timeout=TIMEOUT_SECONDS, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"id": case["id"], "should_fire": case["should_fire"],
                    "fired": False, "status": "error", "detail": str(exc)}
    if completed.returncode != 0:
        return {"id": case["id"], "should_fire": case["should_fire"], "fired": False,
                "status": "error", "detail": completed.stderr.strip()[:200]}
    return {"id": case["id"], "should_fire": case["should_fire"],
            "fired": fired(completed.stdout), "status": "ok", "detail": ""}


def score(results):
    """Precision, recall and the confusion matrix over the non-errored cases.

    A case whose `claude` invocation failed is counted under `errors` and left
    out of both ratios: an infrastructure failure says nothing about whether
    the skill's description is right.
    """
    scored = [result for result in results if result["status"] == "ok"]
    true_positive = sum(1 for r in scored if r["should_fire"] and r["fired"])
    false_positive = sum(1 for r in scored if not r["should_fire"] and r["fired"])
    false_negative = sum(1 for r in scored if r["should_fire"] and not r["fired"])
    true_negative = sum(1 for r in scored if not r["should_fire"] and not r["fired"])
    predicted = true_positive + false_positive
    actual = true_positive + false_negative
    return {
        "scored": len(scored),
        "errors": len(results) - len(scored),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "true_negative": true_negative,
        "precision": true_positive / predicted if predicted else 1.0,
        "recall": true_positive / actual if actual else 1.0,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Measure whether the c4-diagrams skill fires on labelled prompts.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true",
                       help="Print the plan and exit; calls no model")
    group.add_argument("--run", action="store_true",
                       help="Send each prompt to a headless Claude session")
    parser.add_argument("--limit", type=int, default=None, help="Only the first N cases")
    parser.add_argument("--prompts", default=str(PROMPTS), help="The labelled prompt file")
    args = parser.parse_args()

    cases = load_cases(args.prompts)
    if args.limit is not None:
        cases = cases[: args.limit]

    if args.dry_run:
        print(f"{len(cases)} case(s) from {args.prompts}; nothing will be called.\n")
        for case in cases:
            label = "fire" if case["should_fire"] else "quiet"
            print(f"  {case['id']}  [{label:>5}]  {case['prompt']}")
            print(f"            $ {' '.join(command_for(case))}")
        return

    results = []
    for case in cases:
        result = run_case(case)
        results.append(result)
        mark = "ok " if result["status"] == "ok" and result["fired"] == case["should_fire"] else "MISS"
        if result["status"] == "error":
            mark = "ERR"
        print(f"  {result['id']}  {mark}  fired={result['fired']}  {case['prompt'][:60]}")

    summary = score(results)
    print(
        f"\nprecision {summary['precision']:.2f}  recall {summary['recall']:.2f}  "
        f"(scored {summary['scored']}, errors {summary['errors']})"
    )
    print(
        f"  TP {summary['true_positive']}  FP {summary['false_positive']}  "
        f"FN {summary['false_negative']}  TN {summary['true_negative']}"
    )
    by_id = {case["id"]: case for case in cases}
    disagreements = [r for r in results
                     if r["status"] == "ok" and r["fired"] != r["should_fire"]]
    if disagreements:
        print("\ndisagreements:")
        for result in disagreements:
            case = by_id[result["id"]]
            print(f"  {result['id']}  expected {'fire' if case['should_fire'] else 'quiet'}, "
                  f"got {'fire' if result['fired'] else 'quiet'}")
            print(f"    {case['prompt']}")
            print(f"    why: {case['why']}")
    errored = [r for r in results if r["status"] == "error"]
    if errored:
        print("\nerrors (excluded from the scores):")
        for result in errored:
            print(f"  {result['id']}: {result['detail']}")


if __name__ == "__main__":
    sys.exit(main())
