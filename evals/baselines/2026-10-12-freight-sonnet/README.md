# Baseline — freight, 2026-10-12 (Sonnet, user-shaped request)

The companion to `2026-10-12-freight-opus`. Same fixture, same gold, same
blind conditions; two things deliberately changed, to see whether the first
1.00 came from the skill or from the way the run was asked for:

- **a smaller model** (Sonnet rather than Opus);
- **a user-shaped prompt** — "give me C4 architecture diagrams for this
  repository, use the skill at `<path>`" — instead of an instruction to follow
  Steps 1–3 to the letter. The first run's prompt nudged; this one does not.

### Scores

| Score | Value |
|---|---|
| recall | 1.00 (14/14 — elements 6/6, relationships 6/6, flow steps 2/2) |
| hallucination | 0 |
| evidence validity | 1.00 (14/14) |
| render pass | ok |

**Skill version:** 3.3.7, as of the SKILL.md *before* B-13
**Gold:** `evals/gold/freight.json`
**Host:** Claude Code, model Sonnet
**Analysed:** `tests/fixtures/repos/freight`

**What stood out**

It reached the same score by a visibly different model. It marked the Redis
status cache `"external": true` — drawn outside the system boundary, on the
README's word that the cache is a managed instance — where the Opus run kept
it inside, on the argument that the system is its only reader and writer.
Both are defensible, and the gold scores them the same: `kind` is recorded but
not matched, by design (see `evals/README.md`). That is the tolerant matcher
earning its keep, not a hole in it.

It also cleared the two traps that matter: the carrier network, which the
detectors do not find at all, and Adminer, which they find and label a
container.

The one thing it reported that the gold does not score: **`render_c4.py` run on
its own does not update `summary.json`.** `summary.json` is written by Step 1,
where the render is facts-only; after Step 3 it still reads
`c4.model: "facts-only"` with its four diagram names, while nine `.mmd` files
sit next to it. Verified on both freight runs (11 files in the other one).

That matters because SKILL.md points the agent at `summary.json` for
`c4.model_status`, which is exactly the field that goes stale. It is a real
wart, it is not in the backlog, and it was found by an eval run rather than by
a test — which is the first thing these runs have paid for beyond a number.

**Caveat:** one run, not a statistical claim.

## After B-13

The same prompt, the same model and the same fixture, re-run against the
SKILL.md that B-13 produced (2,091 words → 1,694, the component-graph line
scoped to Level 3, the detection list and the degraded-run table moved to
assets, a stopping criterion added): **recall 1.00, hallucination 0, evidence
1.00 (13/13), render ok.** Unchanged, which is the whole claim B-13 can make
here — see the headroom note in the sibling Opus baseline.

One qualitative difference worth keeping: that run named the carrier network's
invisibility as "a known blind spot", which is the language of the new
`assets/detection-coverage.md`. The asset is being read and used, not just
linked.
