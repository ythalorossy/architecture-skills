# Contributing

The README is for people *using* the skill. This file is for people changing it.

## Running things

```bash
python3 -m unittest discover -s tests      # the c4-diagrams suite, ~15 s
python3 -m unittest discover -s tests/architecture_review   # architecture-review, its own process
python3 -m unittest discover -s tests -p test_scale.py      # one file
ruff check .                                # lint; CI pins ruff==0.17.0
```

Python 3.11 is the oldest supported interpreter, and both entry points exit 1
on anything older. CI runs the suite on Ubuntu and Windows across 3.11, 3.12
and 3.13, plus a coverage job, the lint job, a job that renders with the real
mermaid-cli, and a guard that 3.10 still fails fast.

Two environment variables change what the suite does:

```bash
C4_UPDATE_GOLDEN=1 python3 -m unittest discover -s tests -p test_output_golden.py
C4_REAL_RENDER=1   python3 -m unittest discover -s tests   # needs Node.js
```

Golden files are generated, never hand-edited. Regenerate them, **read the
diff**, and commit it with the change that caused it. If a diff appears that
your change does not explain, that is the finding — stop and understand it.

## The rules that are not obvious

- **Standard library only** at runtime. `coverage` and `ruff` are dev tools,
  installed in CI. A runtime dependency would have to be installed by every
  agent that ships this skill, on every host, so there are none.
- **Model hints are warnings, never errors.** A hint about the agent's
  `c4-model.json` does not fail a run or escalate a tier. `degraded` means
  "the run finished and something needs attention", and what that was belongs
  in `summary.json`.
- **SVGs render by default.** The report embeds them because most Markdown
  viewers do not draw Mermaid.
- **Every change needs a check that fails before it and passes after it.**
  Write the test first and watch it fail. A test written afterwards passes on
  arrival, which proves nothing about whether it can catch the bug.

## The module map

`skills/c4-diagrams/scripts/` is 25 modules that call each other as plain
functions. Every one carries a docstring saying what it is for
(`tests/test_module_docs.py` fails if a new one does not), so this is only the
shape:

| Layer | Modules |
|---|---|
| Entry points | `analyze_repository.py` (the pipeline), `render_c4.py` (diagrams and the C4 half of the report) |
| I/O floor | `repo_index.py` — one walk, one ignore policy, one cached reader, one skip channel. Everything that touches the filesystem goes through it. |
| Per-ecosystem discovery | `dotnet_projects.py`, `node_projects.py`, `python_projects.py`, `java_projects.py`, `go_projects.py`, joined by `projects.py` |
| Facts | `c4_facts.py` (containers, stores, external systems), `code_facts.py` (endpoints, config, deployment), `code_types.py` (Level 4 types, and the comment/string masker everything else reuses) |
| Output | `generate_docs.py` (the report), `generate_mermaid.py` (the dependency graph), `mermaid_syntax.py` (escaping and ids), `svg_render.py` |
| Checks | `model_check.py`, `diagnostics.py` |

Two things are worth knowing before you edit:

- Modules import through a `try: from scripts.x import … except ImportError:
  from x import …` pair, because the scripts run both as a package and as
  loose files an agent invokes by path. Add new imports to **both** branches.
- `repo_index.py` is the only place allowed to walk or read. A new scanner
  takes an `index` and asks it; it does not call `os.walk` or `read_text`.
  `tests/test_io_budget.py` fails if the repository is walked more than once
  or any file is read twice.

## Adding an ecosystem

1. Write `<name>_projects.py` with `discover_projects(repo_path, index=None,
   collector=None)` returning `{"solutions": [...], "projects": [...]}`. Take
   the index and use it; do not walk yourself.
2. Add one line to `projects.py:discover_all` tagging the result with the
   ecosystem name.
3. Add a fixture under `tests/fixtures/repos/` with at least one producer and
   one consumer, so the edges are asserted and not just the node names.
4. Add it to `FIXTURES` in `tests/test_output_golden.py` and generate the
   golden output.
5. Add a baseline to `tests/test_detectors.py` asserting the project names
   **and** the dependency edges.
6. Name the ecosystem everywhere the others are named: the "no supported
   projects" warning in `analyze_repository.py`, the fallback paragraph in
   `generate_docs.py`, `README.md`, `skills/c4-diagrams/assets/detection-coverage.md`,
   and the `longDescription` in each plugin manifest.

## Releasing

One version string is repeated across nine files: `.claude-plugin/plugin.json`,
`.claude-plugin/marketplace.json`, `plugin.json`, `.cursor-plugin/plugin.json`,
`.codex-plugin/plugin.json`, `gemini-extension.json`, `package.json`, the
`SKILL.md` metadata, and `generate_docs.GENERATOR_VERSION`. Bump them together
— `tests/test_versions.py` fails if they differ — add the `CHANGELOG.md` entry
under a new heading, and publish a GitHub release for the tag.

CHANGELOG entries describe the user-visible symptom, not the patch. Read the
existing ones before writing a new one; "the folder overview no longer drops
dependencies" is the voice, not "fixed `group_edges`".

## The architecture-review skill

It is judgment on top of evidence, so the work splits the same way:

- `skills/architecture-review/scripts/signals.py` holds one detector per kind of signal. A detector returns facts with `file:line` and never a secret's value; it does not rank or word a finding. To add one, write the detector, add it to `DETECTORS`, add a row to `references/lens-guide.md`, and add a test in `tests/architecture_review/test_signals.py` for what it flags and what it must leave alone.
- The review itself is written by the agent. `skills/architecture-review/assets/example-review.md` is the reference for what a good one looks like. `skills/architecture-review/scripts/check_review.py` is the skill's feedback loop, the way `render_c4.py` is for the C4 model: it lists every problem (a citation past the end of a file, a missing field, a finding no lens cites) until the agent's review is clean. It checks shape and groundedness, never correctness:

  ```bash
  python3 skills/architecture-review/scripts/check_review.py <ArchitectureReview.md> <repository>
  ```

- Its fixtures, helpers and trigger prompts are all under `tests/architecture_review/`; it reads nothing from `tests/` or from c4-diagrams, and `tests/test_skill_isolation.py` fails if that changes.
