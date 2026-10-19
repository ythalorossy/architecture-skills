# architecture-skills

[Agent Skills](https://agentskills.io) for software architecture. It ships two skills:

- **`c4-diagrams`**: analyzes a local repository and produces [C4 model](https://c4model.com/) diagrams, key-flow sequence diagrams, deployment, API and configuration views, and recommendations based on what the analysis found. It reads .NET, Java/Kotlin, Go, Node.js/TypeScript and Python code. It works in Claude Code, Codex, Cursor, Gemini CLI, OpenCode, GitHub Copilot CLI, pi and any other agent that reads `SKILL.md`.
- **`architecture-review`**: a critical review of a repository, built on `c4-diagrams` output. A script collects evidence (hardcoded secrets, shared databases, containers that import each other, missing health checks, and more) with `file:line` on every item; the agent reads it with the code and writes `ArchitectureReview.md`: findings ranked by consequence, each with the scenario, the fix and its tradeoff. A checker (`check_review.py`) verifies the review's citations and structure before it reaches you. See [`skills/architecture-review/assets/example-review.md`](skills/architecture-review/assets/example-review.md). Run `c4-diagrams` on the repository first.

| C4 level | Shows | Where it comes from |
|---|---|---|
| 1 · System context | the system, its users, the external systems it talks to | the agent, from the code and docs, in an editable `c4-model.json` |
| 2 · Containers | what runs on its own (web API, web app, worker, CLI) and its data stores | detected in project files, dependencies, EF Core/DB clients, docker-compose |
| 3 · Components | each container's modules, then the packages/namespaces inside them (Java/Kotlin packages, C# folders, Go packages) and their imports | the code, without tests; the agent describes the important ones |
| 4 · Code | the classes and interfaces of the key components: inheritance, dependencies, public methods | the agent picks the components; the script extracts the types |
| Key flows | 1–3 important requests traced step by step as sequence diagrams | the agent, from the code, in `c4-model.json` |

The report also has sections built straight from the code:

| Section | Contents |
|---|---|
| Deployment | docker-compose services and their dependencies (as a diagram), Dockerfiles (stages, runtime image, ports, entry point), Kubernetes workloads, CI and hosting files |
| API endpoints | HTTP routes from Spring, JAX-RS, ASP.NET (attribute-routed and conventional MVC controllers, minimal APIs), Express/Fastify/Koa/NestJS, FastAPI/Flask/Django, Go net/http, gin, echo and chi |
| Configuration | environment variables the code reads or compose sets, with defaults, and the config files found |
| Technology inventory | runtime, frameworks and key libraries with versions, per container |

**See it:** [`examples/bookshop/ArchitectureReport.md`](examples/bookshop/ArchitectureReport.md) is a complete report for a small synthetic shop (web app, API, database, a search index another team runs, a payment provider).

Each level is its own diagram, so no single picture has to show everything. Diagrams with more than 20 components are split by module or folder, and in dense graphs shortcut edges are hidden.

The full dependency graph stays in an appendix:

| Stack | What becomes a node | What becomes an edge |
|---|---|---|
| .NET | `.csproj` / `.fsproj` / `.vbproj` | `<ProjectReference>` |
| Node.js monorepo | each workspace package | dependency on another workspace package |
| Node.js / TypeScript single package | folders | imports (relative, tsconfig `baseUrl` / `paths`) |
| Python | distributions, or subpackages/modules of a single package | requirements / `import` statements |
| Maven / Gradle | modules / included projects | inter-module dependencies |
| Go | modules (several `go.mod`), or package folders of one module (`cmd/x`, `internal/x`, …) | `require` lines / imports |

The analysis also checks for dependency cycles, projects outside the solution or workspace, unresolved references, and modules that no test imports.

## Install

### Any agent

[`npx skills`](https://github.com/vercel-labs/skills) installs the skills into every Agent-Skills-compatible agent it finds (Codex, Cursor, OpenCode, Gemini CLI, GitHub Copilot, Windsurf, Cline, Claude Code and others):

```bash
npx skills add ythalorossy/architecture-skills          # this project
npx skills add ythalorossy/architecture-skills -g       # your user account
npx skills add ythalorossy/architecture-skills -a codex -a cursor   # chosen agents only
```

It symlinks one copy into each agent's skills folder (`.agents/skills/`, `~/.codex/skills/`, `~/.cursor/skills/`, `~/.config/opencode/skills/`, `~/.gemini/skills/`, `~/.copilot/skills/`, …). Add `--copy` for independent copies. Update later with `npx skills update`.

### Through the agent's own installer

| Agent | Install |
|---|---|
| Claude Code | `/plugin marketplace add ythalorossy/architecture-skills` then `/plugin install architecture-skills@ythalorossy`. Update: `/plugin marketplace update ythalorossy` |
| Codex | `codex plugin marketplace add ythalorossy/architecture-skills`, then `/plugins` → *architecture-skills* → Install |
| Cursor | Clone the repo into `~/.cursor/plugins/local/architecture-skills` and reload the window, or import the repo as a team marketplace |
| Gemini CLI | `gemini extensions install https://github.com/ythalorossy/architecture-skills`. Update: `gemini extensions update architecture-skills` |
| GitHub Copilot CLI | `copilot plugin marketplace add ythalorossy/architecture-skills` then `copilot plugin install architecture-skills@ythalorossy` |
| OpenCode | In `opencode.json`: `"plugin": ["architecture-skills@git+https://github.com/ythalorossy/architecture-skills.git"]` (`"plugins"` on OpenCode 2.0.4+), then restart |
| pi | `pi install git:github.com/ythalorossy/architecture-skills` |

### Manual

Copy `skills/c4-diagrams/` (or any skill folder under `skills/`) into your agent's skills folder (for example `~/.claude/skills/`, `~/.codex/skills/`, `~/.agents/skills/`). Each skill folder is self-contained.

## Updating

Use your agent's update command from the table above — `/plugin marketplace update ythalorossy`, `npx skills update`, `gemini extensions update architecture-skills`. Nothing else is needed: no command or option has ever been removed, so anything you were running keeps working, and an existing `architecture-docs/` folder is read as it is. Your `c4-model.json` is never rewritten by a run, so the descriptions, people and flows you wrote survive every update.

After updating to 3.5.0, a second skill, `architecture-review`, is installed with the plugin, and a request for an architecture review goes to it instead of `c4-diagrams`. It reads `c4-diagrams`' output, so run that first. Nothing `c4-diagrams` does or writes has changed. See the [CHANGELOG](CHANGELOG.md#upgrading-from-34x).

After updating to 3.4.0, the first run redraws every diagram (each now carries a title) and warns once per key flow that carries no `evidence`, which no model written before 3.4.0 could. That is a warning, not an error: the run still reports `ok`. See the [CHANGELOG](CHANGELOG.md#upgrading-from-33x).

## Upgrading from 2.x

Until 2.2.0 the repository, plugin and skill were all called `architecture-diagram-generator`. From 3.0.0 the repository and plugin are `architecture-skills` and the skill is `c4-diagrams`, so Claude Code shows `/architecture-skills:c4-diagrams`. The old repository URL redirects to the new one.

```bash
# Claude Code
claude plugin uninstall architecture-diagram-generator@ythalorossy
claude plugin marketplace update ythalorossy
claude plugin install architecture-skills@ythalorossy

# npx skills
npx skills remove architecture-diagram-generator -g
npx skills add ythalorossy/architecture-skills -g
```

Existing `architecture-docs/` output folders and `c4-model.json` files keep working.

## Requirements

| Tool | Required? | Version | Used for |
|---|---|---|---|
| An agent that reads [Agent Skills](https://agentskills.io) (Claude Code, Codex, Cursor, Gemini CLI, OpenCode, Copilot CLI, pi, …) | Yes | any recent | runs the skill |
| Python | Yes | **3.11+ (checked at startup)** | the scripts of both skills (standard library only, no `pip install`) |
| Git | Optional | any | `architecture-review` lists only the files git tracks or would track, so gitignored build output is never scanned; without git it skips known dependency and build folders instead |
| Node.js | Optional | **22.13+** | rendering the diagrams to SVG with [`@mermaid-js/mermaid-cli`](https://github.com/mermaid-js/mermaid-cli) |

**You don't need the toolchain of the repository you analyze.** The analyzer only reads files (`.csproj`, `package.json`, `pyproject.toml`, `pom.xml`, `settings.gradle`, source imports). You can analyze a .NET or Java repository without the .NET SDK, a JDK, Maven or Gradle installed, and you don't need to run `npm install` first.

### Python

Check your version:

```bash
python3 --version
```

- **3.11 or newer**: required (checked at startup).
- **Older than 3.11**: not supported. The CLI exits with a clear message and an install hint naming `uv python install 3.12` and `brew install python` / python.org.

If your system Python is older, install a newer one with your package manager, [python.org](https://www.python.org/downloads/), or `uv python install 3.12`.

> **Windows:** the skill calls `python3`. If only `python` or `py` is on your PATH, install Python from python.org or the Microsoft Store, which provides `python3`, or ask the agent to use `py -3`.

### Node.js and mermaid-cli (optional, for the SVG)

The report embeds the diagrams as SVGs so they show in any Markdown viewer, including VS Code's built-in preview, which doesn't render Mermaid. The analyzer uses `mmdc` if it's on your PATH, and otherwise falls back to `npx -y @mermaid-js/mermaid-cli@12.0.0` (pinned version).

Install mermaid-cli once, globally:

```bash
node --version          # must be 22.13 or newer
npm install -g @mermaid-js/mermaid-cli
mmdc --version
```

Installing it ahead of time is recommended. With the `npx` fallback, the first run downloads mermaid-cli and a headless Chrome (a few hundred MB). Each diagram tries npm's cache first and goes online only if the package isn't cached (`ENOTCACHED`). The timeouts are 180 s per diagram and 600 s for that first download; `C4_SVG_TIMEOUT_PER_DIAGRAM` and `C4_SVG_TIMEOUT_INSTALL` change them.

Each SVG render returns a status: `ok` (SVG written), `syntax-error` (bug in the diagram — fix the model), `timeout` (diagram too complex), `tool-error` (other failure), `missing-tool` (neither mmdc nor npx found), or `skipped` (rendering turned off, or the renderer itself failed to start or timed out on the first diagram). A diagram that fails to render (`syntax-error`, `timeout`, `tool-error`) makes the run `degraded`: it exits 0, sets `status: degraded` in `summary.json` and lists the failure in `warnings`. With `--strict` a degraded run exits 2. A degraded run also comes from files that couldn't be read or parsed, and from an invalid `c4-model.json`.

Use `--no-svg` or set `C4_SVG=0` in the environment to skip all SVG rendering (useful in CI or when Node.js is absent). Without Node.js the analysis still works and the run is still `ok`; the report then contains the Mermaid source instead of images, and the script prints a note.

> **Linux / WSL:** headless Chrome needs some system libraries. If `mmdc` fails with an error such as `error while loading shared libraries: libnss3.so`, install the packages listed in [Puppeteer's troubleshooting guide](https://pptr.dev/troubleshooting#chrome-doesnt-launch-on-linux) for your distribution.

## Usage

Ask your agent, for example:

| Request | Skill |
|---|---|
| *"Generate C4 diagrams for ~/src/my-repo"* | `c4-diagrams` |
| *"Generate an architecture diagram for ~/src/my-repo"* | `c4-diagrams` |
| *"How do the projects in this solution depend on each other?"* | `c4-diagrams` |
| *"Review the architecture of this repository and tell me what to fix first"* | `architecture-review` |
| *"Where is this system fragile? I care most about security and deployment."* | `architecture-review` |

Each skill triggers on requests like its own. `architecture-review` builds on the output of `c4-diagrams`, so run that first on the same repository; when its `c4-facts.json` is missing, the review stops and says so.

### c4-diagrams

You can also run the analyzer directly:

```bash
python3 skills/c4-diagrams/scripts/analyze_repository.py <repo_path> [--output <output_dir>]
```

By default the files are written to `./architecture-docs/<repo name>/` in the current directory, so you can keep, commit or delete them.

Output files:

- `ArchitectureReport.md`
- `c4-facts.json`, `c4-container.*`, `c4-component-<container>.*` (modules), `c4-component-shared.*` (the components more than one container is built from, drawn once), `c4-structure-<container>.*` (packages/namespaces), `c4-structure-shared.*` (the packages inside those shared components), `c4-deployment.*`, and with a model `c4-context.*`, `c4-flow-<flow>.*` and `c4-code-<container>-<component>.*` (Level 4 class diagrams)
- `dependency-graph.mmd` / `.svg` / `.json`, `repository-scan.json`, `summary.json`

Run on its own, the analyzer draws the Container and Component levels from code facts only. Through the skill, the agent also writes `c4-model.json` (people, external systems, component descriptions and key flows, each backed by evidence or marked as an assumption) and draws the System Context level, the flow diagrams and the Level 4 class diagrams of the key components. You can edit `c4-model.json` and redraw every diagram:

```bash
python3 skills/c4-diagrams/scripts/render_c4.py ./architecture-docs/<repo name>
```

The model format is described in [`assets/c4-model-reference.md`](skills/c4-diagrams/assets/c4-model-reference.md).

This is the Container level of the [example](examples/bookshop/ArchitectureReport.md):

![Bookshop containers](examples/bookshop/c4-container.svg)

### architecture-review

The review is written by the agent; the scripts gather evidence and check the result. From your working directory, after `c4-diagrams` has run there:

```bash
python3 skills/architecture-review/scripts/collect_evidence.py <repository>
# the agent reads review-evidence.json and the code, then writes ArchitectureReview.md
python3 skills/architecture-review/scripts/check_review.py ./architecture-docs/<repo name>/ArchitectureReview.md <repository>
```

Output files, next to the c4 output in `./architecture-docs/<repo name>/`:

- `review-evidence.json`: signals (hardcoded secrets in source and config, credentials in connection strings, published data-store ports, containers that run as root, models with no migrations, stores shared by several containers, containers that import each other, missing health checks, unpinned images, endpoints with no authentication marker), each with `file:line` and a confidence and never a secret's value; plus the context (containers, stores, CI and hosting files, documents, and what `c4-model.json` adds) and what the signals cannot see
- `ArchitectureReview.md`: an executive summary, goals and quality attributes, the overall architecture, an analysis per lens (security, data, application, infrastructure), findings ranked High, Medium or Low (each with evidence, scenario, fix, tradeoff and confidence), an action plan, and what was and was not inspected

`check_review.py` lists every problem as a `PROBLEM:` line: a citation past the end of a file or on blank lines, a missing field, findings out of priority order, a finding no lens cites, a signal the review never mentions, a scenario that only restates its signal. The agent fixes each and runs it again until it prints `Review check: ok`. A finished example is [`skills/architecture-review/assets/example-review.md`](skills/architecture-review/assets/example-review.md).

## Command reference

### `analyze_repository.py`

```bash
python3 skills/c4-diagrams/scripts/analyze_repository.py <repository> [options]
```

Scans the repository and writes the facts, the facts-only diagrams and the report. An existing `c4-model.json` in the output folder is kept and used.

| Option | Effect |
|---|---|
| `--output <folder>` | Where to write (default `./architecture-docs/<repository name>/` in the current directory). Refused inside the skill folder |
| `--no-svg` | Don't render SVGs; the report shows the Mermaid source |
| `--strict` | Exit 2 when the run is degraded |
| `--timestamp` | Add a "Generated On" time to the report (off by default so re-runs are byte-identical) |
| `--debug` | Show the full traceback of an unexpected error |

### `render_c4.py`

```bash
python3 skills/c4-diagrams/scripts/render_c4.py <output folder> [options]
```

Checks `c4-model.json` against `c4-facts.json` and redraws every C4 diagram and the report's C4 section.

| Option | Effect |
|---|---|
| `--no-svg` | Don't render SVGs |
| `--facts-only` | Ignore `c4-model.json` and draw from the facts alone |
| `--repo <path>` | Where the repository is, when the output folder was moved away from it (needed for Level 4 and evidence checks) |
| `--strict` | Exit 2 when the model drifts from the code |
| `--debug` | Show the full traceback of an unexpected error |

### `collect_evidence.py`

```bash
python3 skills/architecture-review/scripts/collect_evidence.py <repository> [options]
```

Reads `c4-facts.json` (and `c4-model.json`, when present) and the repository, and writes `review-evidence.json`.

| Option | Effect |
|---|---|
| `--facts <file>` | The c4 facts to read (default `./architecture-docs/<repository name>/c4-facts.json` in the current directory) |
| `--output <folder>` | Where to write `review-evidence.json` (default: the folder holding the facts) |
| `--debug` | Show the full traceback of an unexpected error |

### `check_review.py`

```bash
python3 skills/architecture-review/scripts/check_review.py <ArchitectureReview.md> <repository> [options]
```

Checks a review's structure and citations, prints one `PROBLEM:` line per problem, then `Review check: ok` or `Review check: N problem(s)`. It checks shape and groundedness, not whether a finding is right.

| Option | Effect |
|---|---|
| `--evidence <file>` | The `review-evidence.json` to resolve signal ids against (default: the one beside the review, if any) |
| `--debug` | Show the full traceback of an unexpected error |

### Environment

| Variable | Effect |
|---|---|
| `C4_SVG=0` | Same as `--no-svg`, for both `c4-diagrams` scripts |
| `C4_SVG_TIMEOUT_PER_DIAGRAM` | Seconds per diagram before the renderer is stopped (default 180) |
| `C4_SVG_TIMEOUT_INSTALL` | Seconds for the first `npx` run, which downloads mermaid-cli and Chrome (default 600) |

### Exit codes and status

| | `analyze_repository.py` | `render_c4.py` |
|---|---|---|
| 0 | done (`summary.json` `status` is `ok` or `degraded`) | the model is `ok`, or `drift` |
| 1 | could not run: bad path, Python older than 3.11, unexpected error | the model is `invalid` (facts-only diagrams were drawn), or could not run |
| 2 | degraded, with `--strict` | drift, with `--strict` |

| | `collect_evidence.py` | `check_review.py` |
|---|---|---|
| 0 | `review-evidence.json` written | `Review check: ok` |
| 1 | could not run: missing or unreadable `c4-facts.json`, bad path, Python older than 3.11, unexpected error | the review has problems (listed as `PROBLEM:` lines), or could not run |

`summary.json` `status` is `degraded` when a file couldn't be read or parsed, a diagram failed to render, or `c4-model.json` is invalid; each cause is in `warnings`. A missing Node.js is not degraded. `c4.model_status` is `ok`, `drift` (facts the model doesn't cover yet) or `invalid`.

## Troubleshooting

| You see | What to do |
|---|---|
| `python3: command not found` (often on Windows) | Use `python` or `py -3`, or install Python 3.11+ |
| `ERROR: Python 3.11+ is required (found 3.x)` | Install a newer Python (`uv python install 3.12`, python.org, or your package manager) |
| `NOTE: SVGs not rendered: neither mmdc nor npx is on PATH` | Install Node.js 22.13+ (and ideally `npm install -g @mermaid-js/mermaid-cli`). The analysis itself is complete |
| The first run hangs or ends with `timeout` on every diagram | The first `npx` run downloads mermaid-cli and Chrome. Install mermaid-cli globally, or raise `C4_SVG_TIMEOUT_INSTALL` |
| `tool-error` with `error while loading shared libraries: libnss3.so` (Linux, WSL) | Headless Chrome needs system libraries; see [Puppeteer's troubleshooting guide](https://pptr.dev/troubleshooting#chrome-doesnt-launch-on-linux) |
| `WARNING: c4-container: syntax-error — …` | A label in `c4-model.json` breaks Mermaid; fix that text and re-run `render_c4.py`. Without a model, please open an issue with the `.mmd` file |
| `DRIFT: … was found in the code but is not in the model` | The code changed. Add the fact to `c4-model.json`, or list it in `excluded` with a reason |
| `c4-model.json does not match c4-facts.json:` and exit 1 | The model is invalid; the listed errors name the JSON path and often suggest the right id (`did you mean …?`) |
| `WARNING: no container detected` | Nothing with an entry point, a known framework or a compose service was found. Describe the runnable parts in `c4-model.json` yourself |
| `WARNING: No supported projects found` | The stack isn't one the analyzer reads; see Limitations |
| `repository not found at …; re-run analyze_repository.py or pass --repo <path>` | The output folder moved. Pass `--repo <path to the repository>` to `render_c4.py` |
| `the output folder is inside the skill folder` | Run from your repository's folder, or pass `--output` |
| `c4-facts.json not found; run the c4-diagrams skill on this repository first` | Run `c4-diagrams` on the repository from the same working directory, or pass `--facts <file>` |
| `not a c4-facts.json: it has no 'containers' list` | `--facts` points at the wrong file; give it the `c4-facts.json` that `analyze_repository.py` wrote |
| `PROBLEM: evidence_resolves: …: line N is past the end of …` | A citation's line numbers are wrong; take them from one file at a time (`grep -n`, or `sed -n` on that file) and re-run `check_review.py` |
| `PROBLEM: signals_accounted: signal … is not mentioned` | Cite the signal in a finding's evidence, or say in the review's last section why it was set aside |

## Limitations

- **Detection is pattern-based.** Containers, stores and external systems are found from manifests, framework imports, client libraries, URLs and docker-compose. Something reached only through an in-house wrapper, reflection, or configuration the analyzer doesn't read can be missed. The skill asks the agent to add what it finds in the code, with evidence.
- **Languages:** .NET (C#, F#, VB), Java/Kotlin (Maven, Gradle), Go, Node.js/TypeScript and Python. Other languages are not analyzed (the agent can still model them by hand).
- **Not read:** Terraform and other infrastructure-as-code, runtime behaviour, traffic, and anything outside the repository.
- **Dense graphs hide shortcuts:** when A → B → C is drawn, a direct A → C is left out of component diagrams (the full list stays in `c4-facts.json` and the appendix). Diagrams with more than 20 components are split into parts.
- **The review is static:** nothing is run, so a finding about runtime behaviour is read from the code and says so in its confidence. Production configuration, gateways and anything outside the repository are not seen.
- **Signals are leads, not findings.** They are pattern-based: secrets are matched by name in source and in JSON, YAML, INI, `.env`, `.npmrc` and XML config, and a secret under an unusual name or in another format is missed. Most of a review's value comes from the agent reading the code; on a well-built repository the script may find little.
- **`check_review.py` checks citations and structure, not truth.** A citation inside a file passes even if that line does not support the claim; read the findings before acting on them.
- **Secrets are masked by pattern:** passwords in URLs and connection strings, and values of secret-looking variables, are shown as `***`; other secrets in unusual formats are not detected. Review the report before publishing it.

## Running the tests

The repo ships with a `unittest` suite that exercises the analyzer, the orchestrator and the CLIs with no network and no Node.js required (it runs in a few seconds). From the repository root:

```bash
python3 -m unittest discover -s tests                        # c4-diagrams
python3 -m unittest discover -s tests/architecture_review    # architecture-review, in its own process
```

The two suites run separately because both skills have a Python package named `scripts`. `tests/golden/` holds the expected diagrams (`.mmd`) and `ArchitectureReport.md` for every fixture. When you change the output on purpose, regenerate them and review the diff:

```bash
C4_UPDATE_GOLDEN=1 python3 -m unittest discover -s tests -p test_output_golden.py
```

`C4_REAL_RENDER=1` also runs one test against the real, pinned mermaid-cli (needs Node.js).

## Layout

```
skills/c4-diagrams/
  SKILL.md                 instructions the agent follows (Agent Skills format)
  scripts/                 analyzer (one module per ecosystem), C4 facts and renderer
  assets/                  report template, C4 model reference, dependency-structure checklist, and templates for the system-overview and per-service docs
skills/architecture-review/
  SKILL.md                 the review workflow: collect evidence, read, judge, write
  scripts/                 collect_evidence.py and its signal detectors; check_review.py, the review checker
  assets/                  report template and a finished example review
  references/              what each lens looks for, and what each signal means
examples/bookshop/         complete output for the bookshop test fixture
tests/                     c4-diagrams: unittest suite, fixture repositories, golden outputs
tests/architecture_review/ architecture-review: its own tests, fixtures (a small repository and its frozen c4 facts) and trigger prompts
```

The skills are wrapped once per agent installer; every manifest points at `skills/`:

```
.claude-plugin/            Claude Code plugin + marketplace (the marketplace file is also read by Copilot CLI)
.codex-plugin/             Codex plugin manifest
.agents/plugins/           Codex marketplace manifest
.cursor-plugin/            Cursor plugin manifest
plugin.json                Agent Plugins 1.0 manifest (Cursor, Copilot CLI)
gemini-extension.json      Gemini CLI extension
package.json, index.js     OpenCode plugin (registers skills/) and pi package
```

Changing the skill rather than using it? [CONTRIBUTING.md](CONTRIBUTING.md) has the module map, the rules that are not obvious from the code, and a checklist for adding an ecosystem.

**Releasing:** the version is repeated in `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `plugin.json`, `.cursor-plugin/plugin.json`, `.codex-plugin/plugin.json`, `gemini-extension.json`, `package.json`, the metadata of both `SKILL.md` files and `skills/c4-diagrams/scripts/generate_docs.py`. Bump them together (`tests/test_versions.py` fails if they differ), add a `CHANGELOG.md` entry, and publish a GitHub release for the tag.

## License

[MIT](LICENSE)
