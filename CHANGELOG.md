# Changelog

## Unreleased

### Fixed

- **Dense diagrams no longer drop real dependencies in import cycles.** Hiding an edge A → C because a longer path shows it could follow a path through a cycle back to A and then use A → C itself, so a dependency with no other path disappeared. On a real 218-dependency solution, 17 dependencies were missing.
- **Passwords are never copied into `ArchitectureReport.md` or `c4-facts.json`.** A password inside a URL (`postgresql://user:password@db/…`) or a connection string (`Password=…`) is shown as `***`, whatever the variable is called, and secret-named compose variables (`POSTGRES_PASSWORD`) are stored as `***` in `c4-facts.json`.

## 3.3.3 — 2026-10-11

Recovery release. 3.3.0–3.3.2 hardened the analyzer but also crashed on a common repository shape and reduced and degraded the diagrams. This release fixes those regressions and keeps the hardening.

### Fixed

- **Crash on multi-module Maven/Gradle repositories** (3.3.2). A module with framework dependencies but no `main` class next to a runnable module stopped the analysis with `internal error in scripts.c4_facts:_has_jvm_main: … is not in the subpath of …`, so no C4 output was written.
- **C4 diagrams are rendered to SVG by default again.** Since 3.3.0 the analyzer only rendered `dependency-graph.svg` unless `--svg` was passed, so a report from the analyzer alone showed the C4 diagrams as Mermaid source. `--no-svg` or `C4_SVG=0` turns rendering off; `--svg` is still accepted and does nothing.
- **Diagram quality.** mermaid-cli is pinned to 12.0.0 (it was 10.9.1, which ignored `layout: elk` and clipped subgraph titles). A system font replaces the embedded web font, so SVGs stay around 50 KB.
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
