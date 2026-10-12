# evals

Measures the part of the skill that needs judgement: the `c4-model.json` the
agent writes, and whether the skill fires on the right requests.

This is a development tool. Nothing here ships to a user of the skill, and
nothing here is imported by `skills/c4-diagrams` at runtime.

## Read this first: which fixture a score came from

**bookshop scores are contaminated. freight scores are not.** The two golds
are read differently, and mixing them up is the easiest mistake to make here.

**bookshop.** SKILL.md Step 3 tells the agent to write `c4-model.json` by
following `<skill>/assets/c4-model-reference.md`. That asset is a verbatim copy
of `tests/fixtures/repos/bookshop/c4-model.json`, kept in sync by
`tests/test_reference_example.py`. **The bookshop reference answer ships inside
the skill's own instructions**, so any faithful run on bookshop has already
read it. That is why its baseline scores a perfect 1.00. It is an **upper bound
and a regression anchor only** — a later run carries the same contamination, so
a drop still means something changed in the pipeline, but the number is never a
quality measurement and must not be compared with a score from a real
repository.

**freight** (`tests/fixtures/repos/freight`) exists because of that. It ships
**no** `c4-model.json`, nothing in `skills/` describes it, and it was built to
discriminate: see below. Its scores are real measurements.

## The freight fixture, and the traps in it

A gold only measures something if a bad answer can fail it. The eight
regression fixtures cannot carry one — they are 2–4 manifest files each, so a
gold over any of them covers about two elements and reports 1.00 for almost
any answer. freight is 17 files and is built the other way round: small, but
with three things planted that a careless reading gets wrong.

| Trap | What a careless answer does | How the gold catches it |
|---|---|---|
| **An external system the detectors cannot see.** The carrier network is called through `shared/src/http.ts` with its URL in `CARRIER_API_URL`, so no file that names a host also imports an HTTP client. `external_systems` in the facts is `[]`. | Mirrors the facts and draws a system with no outside dependency at all. | `carrier` is a required element, with a required relationship and a required flow step: missing it costs 3/14. |
| **A development-only container.** `adminer` is a compose service, so it is a container fact like any other. Nothing in the facts marks it dev-only. | Draws it, putting a tool nobody deploys in the container diagram. | `adminer` is a `forbidden` term, so drawing it is a hallucination. Ignoring it instead is drift, which is *also* counted. Only `excluded` with a reason is clean. |
| **A store reached only through wrappers.** Redis is not a compose service; the API reaches it through `freight.storage` and the poller through `@freight/shared`. | Misses it, or hangs it off the wrong container. | `status-cache` is a required element with two required relationships, one per container. |

A library (`@freight/shared`) and a dev-only dependency (`json-server`) are
there to be *not* drawn as containers; both are `forbidden` terms.

The separation is checked, not asserted: `tests/test_eval_fixture_freight.py`
grades an answer that only mirrors `c4-facts.json` and fails if it scores
better than **recall 0.43 with 1 hallucination**. The same file pins the shape
of each trap, so a detector improvement that quietly hands the agent one of
these answers turns the suite red instead of inflating the score.

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
  "Bookshop API Web" claims two and recall is inflated. Matching is greedy
  with no backtracking, so it can under-report recall but never over-report it;
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

- **The bookshop baseline is contaminated** — see the top of this file. It is
  not a quality measurement.
- **The freight baseline has no headroom.** Two independent blind runs, on
  different models and with differently-worded requests, both score 1.00.
  That is a real result — the gold does mark a careless answer down to 0.43 —
  but it means a prompt change can only be checked for *regression* here, not
  for improvement. Buying headroom needs a harder fixture, not a stricter gold.
- **Two repositories, both synthetic.** Both are 17-file fixtures. A good
  score here does not predict a good score on a real repository.
- **One run per baseline.** Each recorded baseline is a reference point, not a
  statistical claim.
- **One host.** The trigger runner speaks to Claude only.
- **A tolerant matcher can be too tolerant.** `match: ["api"]` also matches
  "Payments API". The at-most-one-role rule is the guard; if a real run shows
  it is still too loose, tighten the terms rather than the rule.

## Baselines

`baselines/<date>-<fixture>[-<model>]/` holds the agent's `c4-model.json`, the
`scores.json` it produced, and a README with the commands, the skill version
and what stood out. The graded artifact is kept with its scores so a later
change in a number has a cause that can be read.
