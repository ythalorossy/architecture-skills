# Baseline — freight, 2026-10-12 (Opus, instructed run)

The first baseline on a fixture the skill has **not** seen the answer to.
Unlike `2026-10-12-bookshop`, nothing in `skills/` contains this model:
`tests/fixtures/repos/freight` ships no `c4-model.json`, and the authoring run
was done by a fresh agent that was told not to open `evals/` or
`tests/golden/`. The score below is a real measurement.

### Scores

| Score | Value |
|---|---|
| recall | 1.00 (14/14 — elements 6/6, relationships 6/6, flow steps 2/2) |
| hallucination | 0 |
| evidence validity | 1.00 (17/17) |
| render pass | ok |

**Skill version:** 3.3.7, as of the SKILL.md *before* B-13
**Gold:** `evals/gold/freight.json`
**Host:** Claude Code, model Opus
**Analysed:** `tests/fixtures/repos/freight`

**Commands**

```bash
C4_SVG=0 python3 skills/c4-diagrams/scripts/analyze_repository.py \
    tests/fixtures/repos/freight --output <folder>
# a fresh agent, given only SKILL.md and the fixture, wrote c4-model.json
# and ran render_c4.py (copied here unedited)
python3 evals/grade.py --output <folder> --gold evals/gold/freight.json
```

## Read the 1.00 carefully

A perfect score here does **not** mean what a perfect score on bookshop means,
and it does not mean the fixture failed to discriminate.

- **The gold has teeth.** An answer that mirrors `c4-facts.json` — every
  detected container drawn, no person, no external system, no flow — scores
  **recall 0.43 with 1 hallucination** on this same gold.
  `tests/test_eval_fixture_freight.py` pins that, so the separation is checked
  by CI rather than asserted here.
- **The run cleared the traps on merit.** The agent added the carrier network
  that the detectors miss entirely (`external_systems` is `[]` in the facts),
  put the dev-only Adminer console in `excluded` with a reason, kept
  `@freight/shared` as a component rather than promoting the library to a
  container, and traced both flows.
- **So the ceiling is the task, not contamination.** On bookshop the 1.00 is
  an artefact: the answer is in the instructions. Here it says that a careful
  run of the current skill solves a 17-file repository with three planted
  traps. That is a genuine result, and it is also the limit of what this
  fixture can tell you.

## What this costs B-13

B-13 cannot be shown as an *improvement* against this baseline: the number
starts at the maximum. It can only be a **non-regression** check — if a
wording change makes the skill miss the carrier or draw Adminer, this run
drops and says so.

Buying headroom needs a harder fixture (more containers, a second language
boundary, a genuinely ambiguous ownership question) or a weaker host, not a
different gold. Tightening this gold to force a lower score would be fitting
the test to the answer.

**Caveat:** one run per model, not a statistical claim. See the sibling
`2026-10-12-freight-sonnet` baseline, which repeats it on a smaller model with
a user-shaped prompt and also scores 1.00.
