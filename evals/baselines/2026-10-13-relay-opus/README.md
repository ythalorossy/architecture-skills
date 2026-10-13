# Baseline — relay, 2026-10-13 (Opus, blind run)

The first baseline on `relay`, the fixture BACKLOG B-29 asks for. Blind in the
sense that matters: `tests/fixtures/repos/relay` ships no `c4-model.json`,
nothing in `skills/` describes it, and the authoring agent was barred from
`evals/`, `tests/` (other than the fixture itself), `docs/`, `examples/`, the
CHANGELOG and git history. It never saw the fixture or the gold being written.

### Scores

| Score | Value |
|---|---|
| recall | 1.00 (23/23 — elements 9/9, relationships 8/8, flow steps 6/6) |
| hallucination | 0 |
| evidence validity | 1.00 (26/26) |
| render pass | ok |

**Skill version:** Step 6 branch (`feat/step-6-remaining`)
**Gold:** `evals/gold/relay.json`
**Host:** Claude Code, model Opus
**Analysed:** `tests/fixtures/repos/relay`

**Commands**

```bash
C4_SVG=0 python3 skills/c4-diagrams/scripts/analyze_repository.py \
    tests/fixtures/repos/relay --output <folder>
# a fresh agent, given only SKILL.md and the fixture, wrote c4-model.json
# and ran render_c4.py (copied here unedited)
python3 evals/grade.py --output <folder> --gold evals/gold/relay.json \
    --repo tests/fixtures/repos/relay
```

## What it cleared, and what that means

It cleared all three of the fixture's traps on merit:

- **the queue-only link.** Nothing in the facts relates the router to the
  notifier; the model draws the path through the bus and traces it in a flow;
- **the store another system owns.** It split the single `db-postgresql` fact
  into the routes database and the finance platform's ledger, and drew finance
  as an external system reading the ledger it owns;
- **the three-container flow.** All six required steps.

It also put `mailpit` in `excluded` with a reason rather than drawing it or
dropping it silently, which is the only clean answer for a dev-only container.

**So relay is a ceiling for Opus, as freight is.** That is the honest reading
of a 1.00 and it is written here rather than left for someone to work out: a
prompt change measured on *this model and this fixture* can still only be
checked for regression. See the Sonnet baseline beside this one for where the
headroom actually is.
