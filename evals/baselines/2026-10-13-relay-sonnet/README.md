# Baseline — relay, 2026-10-13 (Sonnet, blind run)

Same fixture, same gold, same constraints as the Opus baseline beside this
one, on a different model. This is the run that shows `relay` has the headroom
BACKLOG B-29 went looking for.

### Scores

| Score | Value |
|---|---|
| recall | **0.91** (21/23 — elements 8/9, relationships 7/8, flow steps 6/6) |
| hallucination | 0 |
| evidence validity | 1.00 (19/19) |
| render pass | ok |

**Skill version:** Step 6 branch (`feat/step-6-remaining`)
**Gold:** `evals/gold/relay.json`
**Host:** Claude Code, model Sonnet
**Analysed:** `tests/fixtures/repos/relay`

## What it missed, and why that is the useful part

Missed: `element finance` and `relationship finance -> ledger-db`.

The model split the two PostgreSQL databases correctly — `db-ledger` is there,
separate from the routes database, which is the hard half of that trap — but it
stopped at the store and never drew the **finance platform that owns it**. The
system that reads our data is as much a part of the picture as the store it
reads, and README.md says so in as many words ("finance reads it to bill the
depots"). Everything else was cleared: the courier, the queue-only path to the
notifier, the SMS provider the detectors cannot see, the six flow steps, and
`mailpit` in `excluded` with a reason.

This is the first blind run on any fixture in this repository that is neither
contaminated nor a perfect score. It is the number a prompt change can be
measured against.
