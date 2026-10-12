# evals

Measures the part of the skill that needs judgement: the `c4-model.json` the
agent writes, and whether the skill fires on the right requests.

This is a development tool. Nothing here ships to a user of the skill, and
nothing here is imported by `skills/c4-diagrams` at runtime.

## Read this first: the baseline is contaminated

`skills/c4-diagrams/SKILL.md:83` tells the agent to write `c4-model.json` by
following `<skill>/assets/c4-model-reference.md`. That asset is a verbatim copy
of `tests/fixtures/repos/bookshop/c4-model.json`, kept in sync by
`tests/test_reference_example.py`. **The bookshop reference answer ships inside
the skill's own instructions**, so any faithful run on bookshop has already
read it. That is why the recorded baseline scores a perfect 1.00.

The baseline is therefore an **upper bound and a regression anchor only** —
a later run on the same fixture carries the same contamination, so a drop
still means something changed in the pipeline. It is **never a quality
measurement**, and a score from a real repository must not be compared with
it. A real quality baseline needs a gold for a fixture that is *not* the
skill's worked example. That fixture does not exist yet.

## The grader

```bash
python evals/grade.py --output <analyzer output folder>
```

The folder must hold `c4-facts.json` and a `c4-model.json` that an agent
wrote. Four scores:

| Score | Means |
|---|---|
| **recall** | how much of `gold/bookshop.json` the model contains — required elements, relationships and flow steps |
| **hallucination** | a count: elements hitting a `forbidden` term, plus the drift `validate` reports for elements that cover no fact and are not marked `assumption` |
| **evidence validity** | the fraction of `evidence` entries pointing at a file and line that exist |
| **render pass** | whether the model renders — `render()` with SVGs off |

It **reports; it never gates.** Exit 0 whatever the scores. It exits 1 only
when it cannot do its job: a missing or malformed gold, a missing output
folder, a missing or unparseable `c4-model.json`.

Grading never modifies the folder it is given: `render()` rewrites the
`c4-*.mmd` files, so the render-pass score runs on a copy.

`--json` emits the scores for a machine. `--gold` and `--repo` override the
defaults.

### Evidence: one place the grader is stricter than the validator

`score_evidence` reuses the skill's own `render_c4._evidence_problem`, so a
model that passes here normally passes the shipped checker. It adds one guard
that runs **before** it, rejecting an entry that is not a string, is blank or
whitespace-only, is an absolute path, or contains a `..` path segment. The
reason: `_evidence_problem("", repo)` resolves to the repository root, which
exists, so a blank entry would otherwise score as valid evidence.

The consequence, stated plainly: **an entry like `api/../web/x.py` is rejected
by the eval although it stays inside the repo and the shipped checker would
accept it.** That is the one known point where the grader is stricter than the
validator it reuses.

## The gold is criteria, not a reference answer

`gold/bookshop.json` lists what any good answer must contain, by **role**,
with accepted synonyms — not one exact model. `tests/fixtures/repos/bookshop/c4-model.json`
is a correct answer and is deliberately *not* the gold: scoring against one
exact model degrades into string matching, and a differently worded but
correct answer would be marked wrong.

Matching rules, in full:

- an element matches a role when any `match` term is a case-insensitive
  substring of its `id` or `name`;
- roles are tried in gold order, candidates in document order, and **an
  element can satisfy at most one role** — otherwise one box called
  "Bookshop API Web" claims two and recall is inflated;
- relationships match by resolved role, **direction significant**;
- a flow-step end is mapped through `components` to its owning container
  *before* the role lookup, because steps name components. The order matters
  when a component key collides with a container id: if the web container owns
  a component literally keyed `bookshop-api`, looking the key up directly would
  resolve the step to the API container instead of to its owner, the web app.
  `test_a_component_key_that_collides_with_a_container_id_resolves_to_its_owner`
  pins this;
- `kind` is recorded but not required to match.

The gold is a maintained artifact, not ground truth. It encodes one view of
a right answer.

## Trigger prompts

```bash
python evals/triggers/run_triggers.py --dry-run   # print the plan, call nothing
python evals/triggers/run_triggers.py --run       # send each prompt to Claude
```

`triggers/prompts.jsonl` holds 33 labelled prompts (19 that should fire, 14
that should not), each with the reason for its label. `--run` sends each to a
headless Claude session. Each case runs in an empty temporary directory with
Bash, Write and Edit disallowed, so firing is observable but the analyzer
never runs on anything. A case whose `claude` call fails is reported as an
error and excluded from precision and recall.

**How firing is detected.** `fired()` parses the event stream and counts only
an event with `type == "assistant"` carrying a `tool_use` block named `Skill`
whose `input.skill` is the skill — either bare `c4-diagrams` or plugin-qualified
`architecture-skills:c4-diagrams`, which is how the skill actually registers.
A plain text scan is wrong: the `system`/`init` event is one JSON line listing
every available tool (including `Skill`) and every available skill (including
`architecture-skills:c4-diagrams`), so it would match every case, negatives
included, and report a fake recall of 1.0.

**Exit codes, and why they differ from the grader.** `run_triggers.py --run`
exits non-zero when nothing was measured (`scored == 0`, for example `claude`
is not on PATH) and prints `n/a` instead of a ratio. `grade.py` is the
opposite: it never gates on a score. A bad score is a result; a run that
measured nothing is an infrastructure failure, and exiting 0 would let it pass
as if it had been measured.

## What CI runs

`tests/test_evals.py`, through the ordinary `unittest discover -s tests`.
Every case runs on canned input or the committed fixture; none calls a model,
touches the network or renders an SVG. `ruff check skills tests evals` covers
this folder.

No threshold here can turn CI red on a quality number.

## Limits

- **The baseline is contaminated** — see the top of this file. It is not a
  quality measurement.
- **One repository.** bookshop is a 17-file synthetic fixture. A good score
  here does not predict a good score on a real repository.
- **One run.** The recorded baseline is a reference point, not a statistical
  claim.
- **One host.** The trigger runner speaks to Claude only.
- **A tolerant matcher can be too tolerant.** `match: ["api"]` also matches
  "Payments API". The at-most-one-role rule is the guard; if a real run shows
  it is still too loose, tighten the terms rather than the rule.

## Baselines

`baselines/<date>-<fixture>/` holds the agent's `c4-model.json`, the
`scores.json` it produced, and a README with the commands, the skill version
and what stood out. The graded artifact is kept with its scores so a later
change in a number has a cause that can be read.
