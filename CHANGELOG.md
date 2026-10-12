# Changelog

## Unreleased

### Fixed

- **A container with no folders is no longer one unreadable diagram.** 44 components in a single group were drawn as one 44-node view with a note saying it was too big to read, because splitting only ever looked at folders — and so did the search for the components everything else depends on. Such a container is now split into views of at most 20 components, by the first path segment of the names when that says something and in dependency order otherwise, and its shared components are still collected in the Shared box.
- **Level 3 says who calls the container.** A container's component diagram drew only its own components and the stores they use: the Web app's Level 3 showed neither the Reader who uses it nor the API it calls, so Level 2 and Level 3 described different systems. The people, containers and systems the model relates to the container are now drawn around its boundary, with the labels Level 2 already uses.
- **Three kinds of unreadable manifest no longer stop the run.** A `pyproject.toml` or `pnpm-workspace.yaml` saved in Latin-1, or a `.csproj` the OS refuses to open, ended the analysis with `ERROR: internal error …` and exit 1. Each is now read through the tolerant reader, recorded, and the run finishes as `degraded`.
- **A repository where nothing is recognised is no longer reported as a clean run.** No manifest and no entry point gave `containers: 0` with `status: ok` and an empty `warnings` list, which looks like an empty repository rather than a failed detection. It now carries a `detection` warning saying what to check, and the run is `degraded`. A repository that is understood but has no runnable part keeps reporting `ok`.
- **A lone `requirements.txt` no longer claims the repository is Python.** A `docs/requirements.txt` pinning a Sphinx build put `Python` in `technology_stack` with no Python source anywhere.
- **The folder overview no longer drops dependencies.** It was built from the reduced edge set, so a dependency hidden at component level because a longer path showed it disappeared from the folder diagram too, where that longer path is not drawn.
- **A code-structure diagram that repeats the module diagram is no longer written.** A container whose modules each hold one package of the same name produced two files, one report section and one `summary.json` entry for the same picture.
- **Code names keep their characters in diagram labels.** Labels were Mermaid markdown strings, so the renderer parsed them as Markdown: `user_service` was drawn as `user_service` with the underscore eaten on the SVG path, and `__main__` came out bold as `main`. Labels are plain now and every character survives, in the `.mmd` files and in the SVGs. The element name is no longer bold.
- **A `;` in a flow participant's name no longer breaks the diagram.** A participant called `Orders; API` ended the sequence diagram with `Parse error on line 3`, losing the whole flow.
- **`#lt;` and `#gt;` no longer appear in the report.** Mermaid's entity codes were applied to Markdown prose, so a description or heading mentioning `<Request>` reached `ArchitectureReport.md` as `#lt;Request#gt;`.
- **The same relationship written twice is reported.** Two records for the same pair of elements are drawn as one arrow, with the second description silently dropped. `validate` now names the pair and the records that hold it.
- **The Executive Summary describes the system, not the package count.** With a full `c4-model.json` the report still opened with "bookshop has 6 projects … The analysis found no structural concerns", counting Python packages as projects and saying nothing about the architecture the model describes. When a model exists the summary now opens with the system's own description and what the model is made of — containers, data stores, external systems, people, relationships and key flows. The dependency-graph checks keep their own sentence underneath, and a repository with no model reads as before.
- **Model mistakes that used to pass in silence now say what is wrong.** A data store the repository itself runs, filed under `external_systems`, was drawn as another team's system with no message. An unknown key on a relationship, a flow or a flow step was dropped on the floor, so a misspelled `technolgy` or `notes` simply never appeared in the diagram. Each is now a warning that names the key and the closest documented one. A relationship that ends on a component id is told to use a flow step, and the message reads `unknown 'to' id 'x'` instead of `unknown to id 'x'`.
- **Unproven elements reach the Assumptions list.** A person, container or external system marked `"assumptions": true` (a typo for `"assumption"`), or carrying neither evidence nor a marking, was left out of the report's Assumptions section, so nothing asked the team to confirm it. Both are listed now, as "unmarked, no evidence".
- **The run says which files it did not read, and where.** A source file past the 2 MB cap was dropped without a word, so the facts were collected from an incomplete picture and nothing said so; it is now listed in `summary.json` under `skipped_files` with the reason `too_large`. A module too large to read no longer ends the run with `internal error … expected string or bytes-like object`. The same cap now applies to the Level 3 and Level 4 scanners, which read any size before.
- **Skipped files and warnings are named the way you name them.** `summary.json` held absolute paths — `/home/you/work/repo/api/pyproject.toml` — which do not match what the report says and leak the machine they were produced on. They are now relative to the repository, with forward slashes, and an unreadable file reports `oserror: Permission denied` instead of repeating the absolute path inside the message. A file read from outside the repository is still named in full.
- **The analyzer prints drift.** `render_c4.py` printed its `DRIFT:` lines and the analyzer filed the same list into `summary.json` and said nothing, so a re-run after the code changed looked clean on screen.
- **A diagram that failed to render says so where the picture would be.** The report fell back to the Mermaid source with no explanation, which looks exactly like a run with rendering turned off. The section now carries a note naming the failure. A machine with no mermaid-cli still gets one note for the whole run, not one per diagram.
- **Strengths describe the architecture, not the packaging.** With a full `c4-model.json` the report still listed "projects with no project references" as a strength — a fact about which Python packages import nothing, offered as architectural praise, with a front-end folder counted as a project. When a model exists the section now reports what the model proves: every fact covered, every container explained, who the system is for, the key flows written down, every container and external system backed by code. Each line is checked, so a thin model gets a short list and says so instead of being flattered. The dependency-graph cycle check keeps its own line, and a repository with no model reads as before.
- **A folder with more components than fit in one diagram is split.** Splitting by size only ever ran on containers with no folders, so a container with one 26-component folder beside a small one still drew the big one whole and unreadable. It is now cut into `folder (1 of 2)` parts like any other oversized view.
- **`dependency-graph.mmd` says what it is.** Every other diagram gained a front-matter title; this one is written by the analyzer, outside the C4 renderer, and was left without one.
- **Go is named where the other ecosystems are.** The "no supported projects" warning and the report paragraph that replaces the Executive Summary listed .NET, Node.js, Python, Maven and Gradle, so a Go repository the analyzer reads perfectly well was told, when it found nothing, that Go is not supported. The plugin's long description left Go out too. Koa is back in the skill's detection list, where the README already had it, and `SKILL.md` links to the README's Troubleshooting table.
- **A folder called `Tests` is test code, like `tests`.** Three scanners compared folder names without lower-casing them, so a repository that capitalises the folder had its test code read as production code: a framework imported only by the tests became the container's technology, a `main` in a test folder made a module look runnable, and a URL in a test configuration file became an external system. A file named `api.test.ts` or `api.spec.tsx` is now test code too.
- **Go `services/` packages are grouped the same way in both views.** `services/billing` and `services/catalog` were two groups at Level 3 and one group called `services` in the code-structure view below it, because the two views carried separate copies of the folder list. They share one now, with the go.mod module line, the requirements file pattern and the list of configuration keys that only mean "a URL".
- **A crash no longer leaves the output folder holding two different runs.** `ArchitectureReport.md`, the scan and the dependency graph were rewritten before the C4 step ran, so an error anywhere after that left a report describing the new code next to diagrams describing the old. The whole run is now built in a temporary folder beside the output folder and moved in only once it succeeded: a failed run leaves the previous one exactly as it was, and leaves nothing behind. Diagrams an earlier run produced and this one did not are removed as before; `c4-model.json` and any other file of yours in the folder are never touched.
- **Model warnings reach the user on the analyzer path.** `analyze_repository.py` computed every `c4-model.json` warning and threw it away: a re-run over an existing model printed its errors and its drift, but not one of the hints that say a key is misspelled, an evidence path points at nothing or an element is unproven. They were only visible to someone running `render_c4.py` by hand. They are now printed as `WARNING:` lines and filed in `summary.json`, under `c4.model_warnings` and in the run's `warnings` list. A warning still does not make the run degraded.
- **A missing key in `c4-facts.json` is named.** Dropping `endpoints`, `configuration` or `deployment` silently removed that section from the report and still exited 0; dropping `data_stores` gave `internal error in __main__:validate: 'data_stores'`. All seven required keys are checked up front and reported as `c4-facts.json: <key> missing; re-run analyze_repository.py`, exit 1.

### Added

- **Every diagram says what it is, and the report says what the shapes mean.** Each `.mmd` carries a front-matter `title`, so a diagram opened or shared on its own is no longer an unlabelled set of boxes, and the renderers draw it above the picture. The C4 section of `ArchitectureReport.md` opens with one Key, listing only the shapes, colours and line styles the diagrams in that report actually use.
- **`render_c4.py` says whether the model is finished, not just whether it is consistent.** The checks could only answer "does this model contradict the code?", so a model with no person, no flows and not one component description passed as `ok` and silently became a diagram of bare package names. A `Coverage:` line now reports how much judgement the model carries — `Coverage: facts 5/5, containers described 4/4, components described 5/5, people 1, flows 2, code 3` — and it is what the skill reads to decide it is done. It prints on `ok` and on drift, and is not written to `summary.json`.

### Changed

- **The diagram legend is called `Diagram key`.** It sat one heading away from `Key flows`, two unrelated sections a word apart.
- **The `layout: elk` header is gone from every diagram.** No pinned renderer ever applied it: rendering with and without it produces byte-identical SVGs, because the bundled mermaid-cli has no ELK engine. The header, and a comment describing a layout that never ran, are removed. Diagrams are unchanged.
- **`SKILL.md` is 1,694 words, down from 2,091, and no longer contradicts itself.** The line telling the agent to treat the component graph as the source of truth is now scoped to Level 3, where it belongs; at Levels 1 and 2 the instruction to add what the detectors missed stands on its own, instead of being cancelled a paragraph later. The detection list moved to `assets/detection-coverage.md`, which now also carries the **blind spots** — a call through an in-house HTTP wrapper, a URL that only lives in an environment variable, a development-only compose service, a multi-distribution Python repository whose component graph cannot go below the distribution. The `summary.json` warning kinds moved to `assets/run-diagnostics.md`. Step 3 gained an explicit finishing line, read off the new `Coverage:` output: `ok`, no drift, warnings resolved, and no short number in the counts of described containers and components, people, flows and `code` entries. And when the user only asked a question, the skill now answers it and asks before writing files into their repository.

### Development

- **Dead code and stale docstrings are gone.** Three functions nothing called (`c4_facts._add`, `code_facts._yaml_block`, `generate_docs.save_report`) are deleted, a one-line indirection is inlined, and two docstrings that described the wrong thing are corrected: the dependency graph does cover Go, and `main_packages` returns 4-tuples. The two colours `render_c4.py` wrote by hand — the dashed boundary and the pale folder box — are in the palette with the others, and a test fails if a new one appears.
- **The agent's model is now scored on a repository the skill has never seen.** `tests/fixtures/repos/freight` is a 17-file fixture built to discriminate rather than to be large: an external system the detectors cannot find (called through a wrapper, its URL only in an environment variable), a development-only compose service that looks exactly like a container, a data store reachable only through two wrappers, and a shared library that must not be promoted to a container. An answer that only mirrors `c4-facts.json` scores recall 0.43 with a hallucination; `tests/test_eval_fixture_freight.py` fails if it ever scores better, and pins the shape of each trap so a detector change cannot quietly hand the agent the answer. Two blind baseline runs are recorded under `evals/baselines/`, on different models and with differently-worded requests. Both score 1.00 — an honest ceiling this time rather than bookshop's contaminated one, and the README says plainly what that does and does not license.
- **The skill's prompt has a lint.** `tests/test_prompt_lint.py` checks the three things nothing else did: every `<skill>/assets/...` pointer resolves to a file, the `description:` is a single-line scalar that still says when *not* to fire, and the file stays inside its 1,700-word budget. The budget is a fixed number, not a ratchet, because a ratchet is how the file reached 2,091 words.
- **The model the agent writes now has a score.** `evals/` holds a criteria gold for the bookshop fixture and a deterministic grader that reports recall, hallucination count, evidence validity and render pass, built on the skill's own `validate` and `_evidence_problem` rather than copies. The grader's own correctness is covered by unit tests in CI; it reports and never gates, so no quality number can turn the build red. A labelled set of 33 trigger prompts (19 should fire, 14 should not) and a Claude runner measure whether the skill fires on the right requests, with a `--dry-run` CI can exercise without calling a model; the runner counts only a real `Skill` tool call, and exits non-zero when nothing was measured. The first baseline run is recorded under `evals/baselines/`. It scores a perfect 1.00 because the bookshop reference answer ships inside the skill's own instructions, so it is a regression anchor, not a quality measurement.

## 3.3.7 — 2026-10-11

### Fixed

- `summary.json` no longer reports a valid model as `invalid` (and the run as degraded) because of a note such as Level 4's "repository not found … pass --repo". Model status now comes only from `render_c4.py`.

### Development

- One code path through the repository index: about 28 `index`/no-index branches, duplicated helpers (`local_tag` ×3, `walk_files` ×2, `TEST_DIRS` ×4) and unused index API removed. Production code is 368 lines shorter; output is byte-identical on every fixture and on three real repositories.
- Comments and tests describe behaviour instead of citing spec ids from a folder nobody else has.
- Tests that passed for the wrong reason were rewritten (re-run, relocation, grep-based budget checks, the adversarial render corpus).
- ruff runs all pyflakes rules and is pinned in CI; a new CI job renders with the real mermaid-cli.

## 3.3.6 — 2026-10-11

### Fixed

- **Python services with only a `requirements.txt` are found.** A repository with `api/` and `worker/` and no `pyproject.toml` or `setup.py` became one container named after the repository with every framework merged, plus a phantom duplicate when docker-compose built them. Each folder with its own `requirements*.txt` is now a candidate service.
- **Large monorepos analyze in seconds.** An npm workspace of 50 chained packages took 300 s; it now takes about 2 s (20 packages: 18 s to 0.7 s), with identical results. Source files over 2 MB are no longer scanned.

### Added

- When nothing runnable is found and the repository is drawn as one box, `summary.json` gets a `detection` warning instead of reporting a clean run.
- **Docs:** a command reference for both scripts (options, environment variables, exit codes, statuses), a troubleshooting table for the messages you can see, a limitations section, and a complete example report in `examples/bookshop/`.

## 3.3.5 — 2026-10-11

### Added

- **The agent's analysis is kept in the report.** `c4-model.json` takes an optional `summary` (`overview`, `findings`, `recommendations`), written into `ArchitectureReport.md` as an "Architecture overview" right after the Executive Summary. Before, the skill's findings only lived in the chat.
- **Model checks suggest fixes.** Unknown ids suggest the closest real one (`did you mean 'bookshop-web'?`); evidence pointing at a file that doesn't exist, or past its end, is a warning; an empty name is invalid; misspelled keys and types, a fact covered twice, and an excluded entry without a reason are warnings.

### Changed

- SKILL.md: the description names flow, deployment and API requests and says what the skill is not for; a step asks what the script missed and to add it with evidence; `python` / `py -3` fallback; the degraded-run instructions are shorter.

## 3.3.4 — 2026-10-11

### Fixed

- **Dense diagrams no longer drop real dependencies in import cycles.** Hiding an edge A → C because a longer path shows it could follow a path through a cycle back to A and then use A → C itself, so a dependency with no other path disappeared. On a real 218-dependency solution, 17 dependencies were missing.
- **Passwords are never copied into `ArchitectureReport.md` or `c4-facts.json`.** A password inside a URL (`postgresql://user:password@db/…`) or a connection string (`Password=…`) is shown as `***`, whatever the variable is called, and secret-named compose variables (`POSTGRES_PASSWORD`) are stored as `***` in `c4-facts.json`.
- **Edge labels say what the code shows.** When several facts link the same two elements, the most specific description wins over a generic one, so compose's "Depends on" no longer hides "Reads/writes" or "Calls /api … [HTTP]" (2 of 5 container edges on the bookshop example were mislabelled), and technologies are combined.
- **Split component diagrams keep dependencies on other parts.** The target is drawn outside the container as a dashed stub saying where it is ("in part 2"). A real .NET solution had 19 such dependencies missing.
- **Shared components are found in dense graphs.** A component used by most others was missed when hiding shortcut edges had removed most of its incoming edges.
- **docker-compose comments** (`api:   # backend`) no longer end up in service names and drop edges; compose is read by one parser.
- **Data stores look the same in every view.** The deployment diagram used its own image list, so `azure-sql-edge` was a database in one diagram and a box in another.
- **Double quotes in labels** show as “…” instead of `&quot;`.

## 3.3.3 — 2026-10-11

Recovery release. 3.3.0–3.3.2 hardened the analyzer but also crashed on a common repository shape and reduced and degraded the diagrams. This release fixes those regressions and keeps the hardening.

### Fixed

- **Crash on multi-module Maven/Gradle repositories** (3.3.2). A module with framework dependencies but no `main` class next to a runnable module stopped the analysis with `internal error in scripts.c4_facts:_has_jvm_main: … is not in the subpath of …`, so no C4 output was written.
- **C4 diagrams are rendered to SVG by default again.** Since 3.3.0 the analyzer only rendered `dependency-graph.svg` unless `--svg` was passed, so a report from the analyzer alone showed the C4 diagrams as Mermaid source. `--no-svg` or `C4_SVG=0` turns rendering off; `--svg` is still accepted and does nothing.
- **Diagram quality.** mermaid-cli is pinned to 12.0.0 (it was 10.9.1, which clipped subgraph titles). A system font replaces the embedded web font, so SVGs stay around 50 KB. (Corrected in 3.3.8: this entry originally said 12.0.0 honours `layout: elk`. It does not — neither version applies it.)
- **SVG rendering is about 2.5× faster.** The batch render introduced in 3.3.0 never worked with the real mermaid-cli and fell back to serial rendering; diagrams now render four at a time. Timeouts are back to 180 s per diagram and 600 s for the first `npx` download.
- **Mermaid ids are unique and readable again.** Two elements whose ids slug alike (`orders-api`, `orders_api`) could merge into one box; ids had become `db_dash_sql_dash_server`. A participant named `box` in a key flow is safe now.
- **Backticks in names and descriptions** no longer break a diagram (they render as apostrophes).
- **`status: degraded` means something to fix.** It covers files that could not be read or parsed, diagrams that failed to render, and an invalid `c4-model.json`, and each cause is listed in `warnings`. A machine without Node.js is no longer degraded (it gets a `NOTE:`). An invalid model now exits 2 under `--strict`, as the help says.
- The Unreviewed facts table names the kind (`data store`, not `data_stor`).
- `RepoIndex` without a diagnostics collector no longer crashes on a skipped file.
- Reports are stamped with the real version (they said 3.2).

### Changed

- `summary.json` `c4.svg` also records the dependency-graph render.

### Development

- CI is green on Linux and Windows, Python 3.11–3.13. The test suite needs no Node.js or network and runs in seconds (it used to start the real renderer).
- Golden files for every generated diagram and report (`tests/golden/<fixture>/output`, and the full pipeline with a model in `tests/golden/bookshop/with-model`); `C4_UPDATE_GOLDEN=1` regenerates them.
- New fixture `maven_layered` reproduces the 3.3.2 crash.
- `tests/test_versions.py` checks that every manifest carries the same version.

## 3.3.0 – 3.3.2

Test suite and CI, Python 3.11 floor with a clear error, tolerant file reading (unreadable files and odd encodings no longer stop the run), safer Mermaid escaping, tiered model validation (`ok` / `drift` / `invalid` with JSON-path messages), re-runs that keep `c4-model.json`, deterministic and relocatable output, `--no-svg`, `--strict`, `--debug`. These versions were tagged but not released on GitHub.

## 3.2.0 and earlier

See the [GitHub releases](https://github.com/ythalorossy/architecture-skills/releases).
