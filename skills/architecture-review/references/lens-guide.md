# Lens guide

What to look for under each lens, beyond the signals the script collects. The signals are leads; the questions below are how you find what a script cannot.

## Reading the evidence

- **From the c4 facts** (what the analyzer detected, which can miss things): `containers`, `data_stores`, `external_systems`, `endpoints_detected`, `compose_services`, `dockerfiles`, `kubernetes_manifests`. An `endpoints_detected` of 0 for a web app usually means its routes were not recognised; find them in the code.
- **From the c4 model** (what the agent that ran c4-diagrams reviewed and added): `model.people`, `model.external_systems`, `model.excluded`, `model.flows`. Where it differs from the facts, prefer the model, and treat its `summary` findings as claims to verify, not conclusions.
- **Found by the collector itself:** `ci_files`, `hosting_files`, `documents`. `documents` lists at most 30, shallowest first; `documents_total` gives the full count.
- **Caps:** a signal lists at most 8 locations; `detail.locations_total` gives the full count when there are more. Search for the rest (`grep -rn` on the setting or pattern) before you count occurrences.
- **Not live:** secrets in commented-out lines and placeholder values (`your-...`, `xxx`, `example`) are not reported.

## Signals and what to check

| Signal kind | Lens | What it shows | Check next |
|---|---|---|---|
| `secret-default` | security | a secret-named variable or setting has a hardcoded value or default, in source or in JSON, YAML, INI, `.env`, `.npmrc` or XML config (value never recorded; a setting repeated per entry, like `CARRIERS.*.PASSWORD`, is one signal with the paths in `detail.settings`) | does production fall back to it silently? is it rotated? |
| `credentials-in-url` | security | a connection string embeds a password, as a URL (`scheme://user:pass@host`) or as key=value (`Host=…;Password=…`) | where else is it copied? who can read this repository? |
| `auth-markers-absent` | security | a container serves endpoints and no auth marker appears (low confidence) | is auth done in a gateway or middleware under other names? |
| `datastore-port-published` | security | a compose data store is reachable from the host | is the host trusted? is the port needed? |
| `runs-as-root` | security | a Dockerfile's final stage never sets a non-root `USER` | what can the process reach? what does the base image default to? |
| `models-without-migrations` | data | persisted models and no migration folder or tool | how does the schema change today, and who runs it? |
| `shared-store` | data | one store or connection setting used by several containers | who owns the schema? what breaks when one side changes it? |
| `cross-container-import` | application | code imports a folder another container owns | does the importer's image even contain that folder? |
| `no-healthcheck` | infrastructure | a Dockerfile defines no HEALTHCHECK | does compose or Kubernetes probe it instead? |
| `unpinned-image` | infrastructure | an image has no tag or uses `latest` | can a rebuild change behaviour without a code change? |

**Where a location points.** For something present, the line that shows it (`datastore-port-published` cites the port mapping). For something absent, where the thing would belong: the final `FROM` of a Dockerfile for `no-healthcheck`, the first endpoint of each file for `auth-markers-absent`. `no-healthcheck` also carries `detail.probe_defined_elsewhere` and `detail.probe_files`: when a probe is defined, the files that define it are listed and the signal is low confidence.

## Data Lens

- Identifies all persisted models, schemas, and DTOs — ORM models, database tables, event schemas, log contracts.
- Finds every data store in use: relational databases, caches, message queues, file stores, object storage.
- Maps which components read from and write to each store, and whether the access is direct or through a repository/abstraction layer.
- Detects schema drift: models that have diverged from the database schema or from an upstream event contract.
- Flags missing or weak constraints: no unique indexes on lookup keys, no foreign keys enforced, no null checks where null is unexpected.
- Looks for secrets or sensitive fields stored in plain text or logged without masking.
- Identifies implicit data ownership: components that reach into another service's data store rather than calling its API.

## Application Lens

- Identifies the top-level components, modules, and service boundaries from the code structure.
- Maps the key request or execution flows through those components — entry points to external calls and back again.
- Detects violations of the stated layering or package structure: imports that skip a layer or reach across a boundary.
- Flags circular dependencies between packages or modules.
- Looks for implicit dependencies: a component that assumes a global state or a side effect from another component.
- Identifies components that have grown too large or serve too many concerns — the "god module" smell.
- Detects missing abstractions: logic that should be behind an interface but is directly coupled to a concrete implementation.

## Security Lens

- Maps all authentication and authorization checkpoints — where identity is established, where permissions are checked, and where they are missing.
- Finds credentials and secrets in code, config files, environment variables, and log output.
- Identifies trust boundaries: calls between services, between a service and its database, between the system and external APIs.
- Detects missing or weak input validation at trust boundaries — especially at public API endpoints.
- Flags the use of insecure defaults: a database connection that skips TLS, a session that does not expire, a secret stored without rotation.
- Looks for over-privileged components: a service or module that has more access than its role requires.
- Identifies missing or broken audit trails: actions that should be logged but are not, or logs that are not immutable.

## Infrastructure Lens

- Maps the deployment topology: what runs where, how services communicate, and what the hosting environment is.
- Finds configuration as code: Dockerfiles, docker-compose files, Kubernetes manifests, CI pipeline configs, Infrastructure as Code.
- Identifies environment variables in use and flags any that should be secrets but are not treated as such.
- Detects hard-coded deployment assumptions: paths, hostnames, ports, or region names that work in dev but not in production.
- Flags missing or misconfigured health checks, graceful shutdown handlers, and retry/dead-letter logic.
- Identifies dependency on external services or CDNs with no pinning or fallback.
- Detects missing redundancy: single-instance services, no failover for data stores, no backup strategy.

## Cross-lens concerns

Check these after the four lenses. They are ordinary findings, not a separate section:

- A documented protection that does not work: a limit, cache, check or guard the docs and tests describe, whose enforcing code does something else. Read the enforcing code, not just its tests; a test that mocks the broken part passes.
- Architecture drift: the documented architecture (c4-diagrams output, README, ADRs) does not match what the code and config show.
- Hidden couplings: two components that appear independent but share an implicit dependency — a global config, a convention, a deployment-time injection.
- Trust assumption violations: a call crosses a trust boundary without the check the architecture implies should be there.
- Implicit deployment assumptions: the code assumes a specific runtime environment (a particular OS, a mounted volume, a pre-populated cache) that is not reflected in the infrastructure config.
- Data-flow gaps: data that moves from one component to another but the flow is not reflected in the architecture model or documented in the code.
