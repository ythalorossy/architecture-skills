# Changelog

## Unreleased

### Fixed

- **Three kinds of unreadable manifest no longer stop the run.** A `pyproject.toml` or `pnpm-workspace.yaml` saved in Latin-1, or a `.csproj` the OS refuses to open, ended the analysis with `ERROR: internal error …` and exit 1. Each is now read through the tolerant reader, recorded, and the run finishes as `degraded`.
- **A repository where nothing is recognised is no longer reported as a clean run.** No manifest and no entry point gave `containers: 0` with `status: ok` and an empty `warnings` list, which looks like an empty repository rather than a failed detection. It now carries a `detection` warning saying what to check, and the run is `degraded`. A repository that is understood but has no runnable part keeps reporting `ok`.
- **A lone `requirements.txt` no longer claims the repository is Python.** A `docs/requirements.txt` pinning a Sphinx build put `Python` in `technology_stack` with no Python source anywhere.
- **The folder overview no longer drops dependencies.** It was built from the reduced edge set, so a dependency hidden at component level because a longer path showed it disappeared from the folder diagram too, where that longer path is not drawn.
- **A code-structure diagram that repeats the module diagram is no longer written.** A container whose modules each hold one package of the same name produced two files, one report section and one `summary.json` entry for the same picture.
- **Code names keep their characters in diagram labels.** Labels were Mermaid markdown strings, so the renderer parsed them as Markdown: `user_service` was drawn as `user_service` with the underscore eaten on the SVG path, and `__main__` came out bold as `main`. Labels are plain now and every character survives, in the `.mmd` files and in the SVGs. The element name is no longer bold.
- **A `;` in a flow participant's name no longer breaks the diagram.** A participant called `Orders; API` ended the sequence diagram with `Parse error on line 3`, losing the whole flow.
- **`#lt;` and `#gt;` no longer appear in the report.** Mermaid's entity codes were applied to Markdown prose, so a description or heading mentioning `<Request>` reached `ArchitectureReport.md` as `#lt;Request#gt;`.
- **A missing key in `c4-facts.json` is named.** Dropping `endpoints`, `configuration` or `deployment` silently removed that section from the report and still exited 0; dropping `data_stores` gave `internal error in __main__:validate: 'data_stores'`. All seven required keys are checked up front and reported as `c4-facts.json: <key> missing; re-run analyze_repository.py`, exit 1.

### Changed

- **The `layout: elk` header is gone from every diagram.** No pinned renderer ever applied it: rendering with and without it produces byte-identical SVGs, because the bundled mermaid-cli has no ELK engine. The header, and a comment describing a layout that never ran, are removed. Diagrams are unchanged.

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
