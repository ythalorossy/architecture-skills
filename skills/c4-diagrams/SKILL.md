---
name: c4-diagrams
description: Use when the user asks for architecture documentation, C4 diagrams, the key request flows of a codebase as sequence diagrams, a deployment, API or configuration overview, a dependency graph or diagram, an architecture review, or an explanation of how a repository's projects, packages or modules fit together. Works on local repository paths (.NET, Java/Kotlin, Go, Node.js/TypeScript, Python). Not for a quick question about one file or import, for changing code, or for diagrams unrelated to a codebase.
license: MIT
compatibility: Requires python3 (3.11+, checked at startup). Node.js with @mermaid-js/mermaid-cli is optional, for SVG rendering.
metadata:
  author: ythalorossy
  version: "3.3.5"
---

# Architecture Diagram Generator

Turn a repository into C4 diagrams (system context, containers, components, code structure), key-flow sequence diagrams, deployment, API and configuration views, and evidence-based recommendations.

## How the work is split

| Level | Shows | Comes from |
|---|---|---|
| 1 · System context | the system, the people using it, the external systems it talks to | **you**, in `c4-model.json` |
| 2 · Containers | what runs on its own (web API, web app, worker, CLI) and the data stores | the script finds them; you name and describe them |
| 3 · Components | inside each container: its modules, then the packages/namespaces inside them and their imports | the script, from the code; you describe the important ones |
| 4 · Code | the classes and interfaces of 2–5 key components: inheritance, dependencies, public methods | **you** pick the components in `c4-model.json` `code`; the script extracts the types |
| Key flows | 1–3 important requests traced step by step (sequence diagrams) | **you**, in `c4-model.json` `flows` |
| Deployment | docker-compose services, Dockerfiles, Kubernetes, CI and hosting files | the script |
| API, configuration, inventory | HTTP routes, environment variables with defaults, frameworks and versions | the script |
| Appendix | every project/module and reference, tests included, plus the automated checks | the script |

The script does the parts that are objective, and every item it finds carries `file:line` evidence. You add the parts that need judgement (who uses the system, what each external system is for, descriptions). `render_c4.py` checks your model against the facts and draws all levels in one style.

### What the script detects

- **Containers:** .NET `Sdk.Web`/`Worker`/Functions/`Exe` projects; Spring Boot/Quarkus/Micronaut modules with a main class or boot plugin (library modules are not containers); Go `package main` folders; Python packages using FastAPI/Flask/Django/Streamlit/Gradio/MCP/Celery or declaring `[project.scripts]`; Node.js packages using Express/Nest/Next/React/Vue/MCP or declaring `bin`; docker-compose services (a `build:` context is matched to the container below it).
- **Data stores:** EF Core providers, Spring Data templates (`RedisTemplate`, `MongoTemplate`, `KafkaTemplate`…), DB/cache/queue clients in Python, Node.js and Go, Maven/NuGet drivers, docker-compose images.
- **External systems:** SDKs (Anthropic, OpenAI, AWS, Stripe, Sentry, Microsoft Graph…), URL hosts in files that use an HTTP or SOAP client (URLs in comments are skipped), and URL settings in `appsettings*.json`, `application*.yml`/`.properties` and `config.yml`.
- **Links between containers:** compose `depends_on`, and front-end dev-server proxies (Vite, webpack, Next.js rewrites, CRA `proxy`) to the back end.
- **Components:** the modules each container is built from (projects, Maven/Gradle modules, Go packages, Python/TS folders), and inside them the code structure: Java/Kotlin packages, C# namespaces and Go packages grouped below each module's root, with import edges. Stores and external systems attach to the package that uses them. Tests and third-party code (`vendor/`, `wwwroot/lib`, `*.min.js`) are left out; dense graphs hide shortcut edges; more than 20 components are split per module or folder.
- **Report sections:** HTTP endpoints (Spring, JAX-RS, ASP.NET attribute and conventional `{controller}/{action}` routes, Express/Fastify/Nest, FastAPI/Flask/Django, Go), deployment (compose, Dockerfiles, Kubernetes, CI, hosting), environment variables with defaults, and a technology inventory per container.

## Where things are

`<skill>` below is this skill's folder: the folder that holds this `SKILL.md`. When the skill loads, the harness shows its base directory. Use that absolute path wherever `<skill>` appears. The working directory is the user's repository, so a bare `scripts/…` or `assets/…` path does not resolve. Every command below uses `<skill>` for that reason.

The commands use `python3`. If it isn't on the PATH (common on Windows), use `python` or `py -3`; the scripts need Python 3.11+ and say so if it's older.

## Step 1 — Run the analysis

```bash
python3 "<skill>/scripts/analyze_repository.py" "<repository_path>"
```

- Quote paths: repository and folder names may contain spaces.
- Run it from the user's current working directory. By default the files go to `./architecture-docs/<repository name>/` there, so the user can keep, commit or delete them. Pass `--output <directory>` only if the user named another location. Never write into the skill folder.
- It writes `c4-facts.json`, facts-only C4 diagrams (`c4-container.*`, `c4-component-*.*`, `c4-structure-*.*`, `c4-deployment.*`, each as `.mmd` and `.svg`), `ArchitectureReport.md`, `dependency-graph.*`, `repository-scan.json` and `summary.json`.
- Diagrams are rendered to SVG with `mmdc` or `npx @mermaid-js/mermaid-cli@12.0.0` (pinned) and embedded in the report as images. Without Node.js the run prints a `NOTE:` and the report shows Mermaid source instead; tell the user. `--no-svg` or `C4_SVG=0` turns rendering off.

### Check `summary.json`

`status: "degraded"` means something needs attention; every cause is in `warnings` (each with `kind`, `message`, `source` and maybe `path`):

- **`parse`** / **`skipped`** (also listed in `skipped_files`): files that could not be parsed or read. Tell the user which and why.
- **`render`**: a diagram failed to render. A `syntax-error` is a bug in the diagram, often a label in the model: fix it and re-run `render_c4.py`. Report `timeout` and `tool-error` to the user.
- **`model_error`** (`c4.model_status: "invalid"`): the model fell back to facts-only. Fix the listed errors and re-run `render_c4.py`.

`c4.model_status: "drift"` (not degraded) means new facts aren't in the model yet: add them, or list them in `excluded` with a reason, and re-run `render_c4.py`. With `--strict` a degraded run exits 2; otherwise 0.

## Step 2 — Read the facts and the code

Read `summary.json` and `c4-facts.json`. Then read enough code to answer what the facts can't:

- **Who uses it?** Look at controllers or routes, auth handlers, UI, CLI commands, README.
- **What is each external system for?** Open the evidence lines.
- **Is each fact real?** For example, a `requests` call in a one-off script isn't a system dependency, and `excluded` is the place for it.
- **What does each container and key component do?** Open the code components in `c4-facts.json` (`containers[].code_components`) and read a file or two per package, so you can describe them.
- **What are the main flows?** Follow 1–3 important requests from the entry point (an endpoint in `endpoints`, a UI action, a CLI command or a scheduled job) through the components to the stores and external systems.
- **Which components matter most?** Pick 2–5 that hold the core behaviour (a workflow engine, the migration agents, a client wrapper) for Level 4, and read their main classes.
- **What did the script miss?** The detectors are pattern-based. When the code shows a container, store, external system or link the facts don't have (a queue consumer, a scheduled job, a gRPC or in-house SDK client, a call through a wrapper), add it to the model with `evidence` pointing at that code. Recall matters as much as precision: a missing payment provider misleads more than a mislabelled one.

Treat the component graph as the source of truth for which components and edges exist.

## Step 3 — Write `c4-model.json` and draw

Write `c4-model.json` in the output folder, following `<skill>/assets/c4-model-reference.md`. In short:

- cover every fact id, either as an element, in an element's `facts` list, or in `excluded` with a reason;
- data stores go in `containers` with `"type": "database"`;
- every element has `evidence`, or `"assumption": true`;
- add a one-line description for each important component, using the ids from `c4-facts.json` (module ids, and code ids such as `weather-api::controller`);
- add 1–3 `flows`: each a named, ordered list of steps between people, containers, external systems or components. Use component ids for the steps inside a container, so the flow shows the code path.
- add `code`: 2–5 key components (component ids from `c4-facts.json`), each with a one-line `description` and, optionally, the `types` to center the class diagram on.
- add `summary`: an `overview` paragraph, your `findings` (each tied to a `file:line`) and `recommendations` (each backed by a finding). It becomes the report's "Architecture overview", so the analysis stays with the diagrams.

Then run:

```bash
python3 "<skill>/scripts/render_c4.py" "<output folder>"
```

It reports the model in three tiers. `ok` draws the model as written. `drift` (a fact the code has and the model does not cover yet) prints one `DRIFT:` line per item and exits 0; add each item to the model, or list it in `excluded` with a reason. `invalid` (a JSON syntax error with its line and column, a wrong-typed section with its JSON path, an unknown id, or a duplicate id) draws the facts-only diagrams and exits 1: fix the model and run it again. Use `--strict` to exit 2 on drift as well. Messages suggest the likely fix (`did you mean 'bookshop-web'?`), and evidence that points at a missing file or line is a warning. Fix every error, resolve every drift item, and fix or justify each warning before you finish.

It prints a warning per diagram that fails to render (a `syntax-error` is a bug in the diagram: fix the model), and rewrites the C4 section of `ArchitectureReport.md` and the `c4-*.mmd`/`.svg` files.

If `c4-model.json` already exists from an earlier run, it was kept (and maybe edited by the user). Update it rather than rewriting it from scratch, and keep the user's wording.

## Step 4 — Report to the user

Your overview, findings and recommendations are already in `ArchitectureReport.md` (from `summary`). In the chat, give the short version:

1. **What the system is**: 2–3 sentences, from the Context level.
2. **Diagrams**: the Context and Container Mermaid blocks inline, then list the component, code, flow and deployment diagrams by file.
3. **Findings**: the most important ones, each tied to a concrete element, component, file or edge. Mark which came from the automated checks (appendix) and which are your judgement. For a cycle, name an import that causes it.
4. **Assumptions**: the elements you marked as assumptions, for the user to confirm.
5. **Recommendations**: only ones backed by a finding.
6. **Artifacts**: the output folder path and `ArchitectureReport.md`. It's the user's to keep, commit, or delete (or add to `.gitignore`), and `c4-model.json` can be edited and re-rendered with `render_c4.py`.

For an architecture review, walk through `<skill>/assets/architecture-review-checklist.md`. If the user wants a system overview or per-service docs, fill `<skill>/assets/system-overview-template.md` / `<skill>/assets/service-template.md` from what you found.

**If nothing was detected** (no containers and an empty graph, e.g. an unsupported stack): build the picture from the source yourself, write the model by hand, and tell the user the diagrams were derived manually rather than by the script.

## Common mistakes

| Mistake | Fix |
|---|---|
| Stopping after Step 1 | The facts-only diagrams have no people, no purposes, no flows and no Context level. Write the model. |
| Findings only in the chat | The chat is gone when the session ends. Put them in `summary` so they're in the report. |
| Modelling only what the script found | Add what the code shows and the facts missed, with evidence. |
| A model with no `components` descriptions or `flows` | Level 3 then shows bare package names. Describe the important components and trace at least one flow. |
| Inventing people, external systems or flows | Only what code, config or docs support; mark the rest `"assumption": true`. |
| Reporting "0 projects, no concerns" as healthy | Empty graph = not analyzed. Analyze manually. |
| Calling the architecture healthy because the checks passed | The checks cover reference hygiene and cycles only. Say what you actually inspected. |
| Treating "outside solution/workspace" as dead code | Examples, fixtures and tooling are often standalone on purpose. Check before recommending deletion. |
| Inventing layers ("Controller → Service → Repository") the code doesn't have | Name only components and edges in the facts or that you saw in the code. |
| Writing output to a temp or scratchpad folder | The user can't find it later. Use the default `./architecture-docs/` or the location they named. |
| Level 4 on model or DTO folders | They only hold data. Pick components with behaviour: services, engines, agents, clients. |
