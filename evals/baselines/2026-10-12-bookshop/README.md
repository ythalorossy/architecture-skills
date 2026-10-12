# Baseline — bookshop, 2026-10-12

> ## ⚠ Read this before reading the scores
>
> **This is NOT a quality measurement.** The scores below are an **upper bound,
> measured with the worked example visible to the agent.**
>
> **Cause.** `skills/c4-diagrams/SKILL.md:83` tells the agent to write
> `c4-model.json` by following `<skill>/assets/c4-model-reference.md`. That
> asset's own header declares it "a copy of
> tests/fixtures/repos/bookshop/c4-model.json", and
> `tests/test_reference_example.py` fails if the two diverge. **The bookshop
> reference answer therefore ships inside the skill's own instructions.** Any
> faithful run of the skill on bookshop has already read the answer. This is
> structural, not an accident of this run.
>
> **What this baseline IS good for.** A *regression anchor*: future runs on this
> fixture carry identical contamination, so a diff against it still detects
> changes in the output pipeline (analyzer, model validation, grader, render).
>
> **What it is NOT good for.** It supports no claim about quality on an unseen
> repository. Do not compare a score from a real repository against it; a
> real repo scoring 0.6 would not mean the skill regressed.
>
> **Deferred work.** A meaningful quality baseline needs a fixture that is
> **not** the skill's worked example. That fixture does not exist yet.

| Score | Value |
|---|---|
| recall | 1.00 (13/13 — elements 6/6, relationships 5/5, flow steps 2/2) |
| hallucination | 0 |
| evidence validity | 1.00 (11/11) |
| render pass | ok |

**Skill version:** 3.3.7 (`skills/c4-diagrams/SKILL.md` `metadata.version`)
**Repository commit:** d563a9e
**Gold:** `evals/gold/bookshop.json`
**Host:** Claude Code
**Analysed:** `tests/fixtures/repos/bookshop`

**Commands**

```bash
python skills/c4-diagrams/scripts/analyze_repository.py tests/fixtures/repos/bookshop --output <folder>
# the agent then wrote c4-model.json (copied here unedited)
python evals/grade.py --output <folder>
python evals/grade.py --output <folder> --json > evals/baselines/2026-10-12-bookshop/scores.json
```

The grader is deterministic: re-running `--json` and diffing against
`scores.json` produces no output.

**What stood out**

The agent did not copy the reference. It added a `search-books` flow, added
`bookshop.payments` as a second code component, and routed the payment call
`bookshop.orders -> bookshop.payments -> provider` instead of straight from
orders to the provider. It still scored 13/13. The gold's role-based matching
resolved `bookshop.payments` through its owning container to the `api` role, so
`api -> payments` still matched. That is the tolerant matching working as
designed, and evidence the gold is not merely string-matching ids.

The scores do not capture the extra material (the added flow and component);
hallucination counts only claims that fail evidence checks, and those passed.

**Caveat:** one run, not a statistical claim. N=3 is deferred — see the
BACKLOG. bookshop is a 17-file synthetic fixture whose answer is visible to the
skill, so a good score here does not predict a good score on a real repository.
