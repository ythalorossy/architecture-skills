# Spec assignments (Phases 5–6)

Lead decisions that every spec follows:
- **D1:** Python floor 3.11+, with a fail-fast check and install hints; CI matrix 3.11–3.13.
- **D2:** A degraded run exits 0 and writes `status: degraded` plus `warnings` to `summary.json`. Exit 2 only under `--strict` or in CI; exit 1 means the run failed.
- **D3:** By default the analyzer renders only `dependency-graph.svg`; the facts-only C4 SVGs are opt-in with `--svg`. `--no-svg` turns off all rendering.
- **D4:** Output writes replace files atomically one at a time, only for files listed in a generated-files manifest. Files the tool didn't write are never deleted.
- **D5:** Validation results are tiered as `invalid` (blocks the render), `drift` (renders with warnings) and `warnings`. Evidence checks are warnings until the evidence format is canonical.
- **D6:** Stdlib-only runtime dependencies stay as they are. Dev-only tooling (a linter, coverage) is allowed.
- **D7:** No code in specs or plans. Plans name exact files, functions, test names, and the behaviour each test asserts.

| Spec | Title | Merges findings | Author | Status |
|---|---|---|---|---|
| SPEC-01 | Replace private-repo example with a synthetic, validating example | PE-10 | prompt-engineering-specialist | shipped (in `60a2404`) |
| SPEC-02 | Test harness, CI, Python 3.11 floor and CLI error UX | REL-11, PE-11 Tier 0, DOC-03 (CI part), REL-13, DOC-08 (guard), CQ-14 (linter) | reliability-engineer | shipped (8/9 ACs; AC2 partial — `code_facts.py` 69%) on `spec-02-test-harness-ci` |
| SPEC-03 | Shared repository index with tolerant I/O | ARC-02, REL-01, REL-02, CQ-06 (helpers out of `dotnet_projects.py`), CQ-07 (I/O helpers) | reliability-engineer (reassigned) | pending |
| SPEC-04 | Single safe Mermaid emitter (ids and escaping) | DIA-01, REL-06, DIA-05, DIA-06, DIA-13, CQ-07 (escapers), REL-05 (internal id collision), CQ-13 (palette) | architecture-diagram-engineer | pending |
| SPEC-05 | Bounded, diagnosable SVG rendering pipeline | DIA-02, DIA-03, DIA-04, REL-07, REL-08, PE-09 (`--no-svg`), DOC-09 (flags), D3 | architecture-diagram-engineer | pending |
| SPEC-06 | Validator robustness and tiered results | REL-04, PE-01, D5 (tiers), REL-13 (render CLI part) | reliability-engineer | pending |
| SPEC-07 | Model contract enforcement (anti-hallucination) | PE-02, REL-05, PE-05, PE-03 | prompt-engineering-specialist | pending |
| SPEC-08 | Re-run semantics, degraded channel and relocatable output | ARC-07, REL-09, PE-12, ARC-06, REL-12, D2 | reliability-engineer | shipped (14ffcbc) |
| SPEC-09 | Versioned facts, model and summary contracts | ARC-05, CQ-09, CQ-10 | prompt-engineering-specialist (reassigned) | pending |
| SPEC-10 | Atomic output writes and report ownership | REL-03, ARC-08, D4 | reliability-engineer | pending |
| SPEC-11 | Fact-collection performance and `collect_facts` decomposition | ARC-01, CQ-08, REL-10, CQ-03 | code-quality-engineer | pending |
| SPEC-12 | Unify compose parsing, store tables and test detection | CQ-01, CQ-02, CQ-04 | code-quality-engineer | pending |
| SPEC-13 | Layered packages, per-layer registries and a unique package name | ARC-03, ARC-04, ARC-09, CQ-05, CQ-06 (remainder) | code-quality-engineer (reassigned) | pending |
| SPEC-14 | Python discovery without manifests; requirements-only services | ARC-10, ARC-12 | architecture-diagram-engineer (reassigned) | pending |
| SPEC-15 | Code hygiene: dead code, nesting, magic values, linter rules | CQ-11, CQ-12, CQ-13 (non-palette), CQ-14 | code-quality-engineer | pending |
| SPEC-16 | Agent workflow quality: relationship recall, determinism, facts brief, trigger | PE-04, PE-06, PE-07, PE-08, PE-13 | prompt-engineering-specialist | pending |
| SPEC-17 | Skill evaluation suite (trigger and end-to-end gold fixtures) | PE-11 Tiers 1–2, DOC-07 (shared fixtures) | prompt-engineering-specialist | pending |
| SPEC-18 | Diagram semantics: reduction order, split edges, legend, shared libraries | DIA-07, DIA-08, DIA-09, DIA-10, DIA-11, DIA-12 | architecture-diagram-engineer | pending |
| SPEC-19 | Single-source version, release automation, changelog, manifest generation | DOC-01, DOC-02, DOC-05, ARC-11 | code-quality-engineer (reassigned) | pending |
| SPEC-20 | Contributor docs: CONTRIBUTING, ARCHITECTURE, ecosystem guide, docstrings | DOC-03, DOC-04, DOC-10, DOC-11 | code-quality-engineer (reassigned) | pending |
| SPEC-21 | User docs: limitations, troubleshooting, example output, README restructure | DOC-06, DOC-07, DOC-08, DOC-09, DOC-12 | architecture-diagram-engineer (reassigned) | pending |

**Files:**
- Spec: `docs/architecture-council/specs/SPEC-NN-<slug>.md`
- Plan: `docs/architecture-council/plans/SPEC-NN-<slug>-plan.md`
