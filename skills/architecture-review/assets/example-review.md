# Architecture Review: architecture-review-mvp

**Date:** 2026-10-17 · **Inputs:** c4-facts.json, review-evidence.json, README.md, api/app.py, api/models.py, api/settings.py, worker/tasks.py, worker/Dockerfile, docker-compose.yml, both pyproject.toml files

## Executive summary

Inventory Tracker is a FastAPI service and a Celery worker that are meant to share one Postgres database. As written, the worker cannot run in its container: it imports the API's code from outside its own build context and points its message broker at `localhost`. The database password is a literal in three places and the schema has no owner or migration path. Fix the worker's startup first, then take the credentials out of the repository, then decide which service owns the database.

## Goals and quality attributes

The README describes a synthetic inventory tracker, so these goals are inferred from the code, not stated: serve inventory over HTTP (`GET /items`) and process items in the background. The qualities that matter most are operability, because both parts are meant to run as containers from `docker-compose.yml`, and changeability, because the API and the worker are separate deployables that should evolve independently. Security matters in the ordinary way for anything that holds a database credential. There is no stated availability or scale target.

## Scope and inputs

The whole repository: two containers (`inventory-api`, `inventory-worker`), one data store (PostgreSQL), no external systems in the c4 facts. No diagrams were used beyond the facts file. The review is static; nothing was run.

## Overall architecture

`inventory-api` is a FastAPI app with one read-only route and a SQLAlchemy model module. `inventory-worker` is a Celery worker with one task. Compose builds each from its own folder and starts a `postgres:16` service named `db`. Both application services are given the same `DATABASE_URL`, so the database is shared. The worker also needs a Redis broker, but compose defines none and the c4 facts list no external system for it, so the broker is a dependency the diagrams cannot show. The code reads as an early skeleton: `get_items()` returns an empty list and nothing imports `api/settings.py`, so the database connection is configured and not yet used.

## Analysis by lens

### Security

The credential handling is the weak point: a password literal appears in compose and as a code default (F3), so a missing environment variable falls back to a development password without any error. The one route has no authentication marker (F4), which is a low-confidence signal. The worker image runs as root (F7). Nothing here parses untrusted input beyond the route's path, so injection risk is currently small.

### Data

One PostgreSQL database is shared by both services and no code owns its schema (F5). The models have no migration tool, and because no code reads the database yet the coupling is latent: it becomes a real cross-service dependency the first time the worker queries `Item`.

### Application

The worker imports `api.app` and `api.models` directly (F1). That couples the two deployables at the source level and, because of the build context, also breaks the worker at start. The worker's only declared dependency is `celery`, so it was never meant to carry the API's libraries.

### Infrastructure

Compose has no `depends_on`, no health checks and no database volume (F6), and the worker's broker address cannot work inside a container (F2). The Dockerfile pins its base image to a minor version, which is reasonable, and `postgres:16` is pinned too.

## Key findings and action items

### F1: The worker imports the API package, which is not in its container image

- **Priority:** High — the worker fails at import time, so no background processing can happen as deployed
- **Lens:** Application
- **Evidence:** `worker/tasks.py:2-3`, `docker-compose.yml:6`, `app-01`
- **Scenario:** Compose builds the worker with context `./worker`, and the Dockerfile copies only that folder. `from api.app import app` and `from api.models import Item` then raise `ModuleNotFoundError` when Celery loads `tasks`, so the container exits at startup. Even with the folder present, importing `api.app` would pull FastAPI and SQLAlchemy into a service that declares only Celery.
- **Fix:** Remove both imports. If the worker needs the `Item` shape, move it to a small shared package that both services install, or pass plain data through the task arguments, which `process_item(item_id: int)` already does.
- **Tradeoff:** A shared package gives one definition of the model and a second thing to version and release. Passing plain data keeps the services independent and means the worker re-reads what it needs.
- **Confidence:** High — the build context and the `COPY` line are both visible, and the import statements are on the cited lines

### F2: The worker's broker address points at its own container

- **Priority:** High — the worker cannot receive tasks even once F1 is fixed
- **Lens:** Infrastructure
- **Evidence:** `worker/tasks.py:5`, `docker-compose.yml:6`
- **Scenario:** `Celery("tasks", broker="redis://localhost")` is evaluated inside the worker container, where `localhost` is the worker itself. Compose defines no Redis service, so there is nothing to connect to. In any environment the broker location is a hardcoded literal, so changing it means editing code.
- **Fix:** Read the broker URL from an environment variable, add a Redis service to compose with that address, and list Redis as a dependency in the c4 model so the diagrams show it.
- **Tradeoff:** One more service to run and secure, and a startup-order dependency that F6 should cover.
- **Confidence:** High — both the literal and the absence of a Redis service are in the cited files

### F3: The database password is committed as a literal and as a silent code default

- **Priority:** High — a missing variable in production would connect with a development password and raise no error
- **Lens:** Security
- **Evidence:** `api/settings.py:4`, `docker-compose.yml:5`, `docker-compose.yml:9`, `sec-01`
- **Scenario:** `settings.py` falls back to a connection string that includes the password when `DATABASE_URL` is unset, and compose repeats the same string for both services. Anyone who can read the repository can log in to the development database, and a deployment that forgets the variable will quietly use the same credentials.
- **Fix:** Remove the default so a missing `DATABASE_URL` fails at startup, and have compose read the password from an untracked `.env` file or a secret. Rotate the committed password.
- **Tradeoff:** Local setup needs one extra step (creating the `.env`), and CI needs the variable supplied.
- **Confidence:** High — the literal appears on the cited lines; whether that password reaches production is unknown

### F4: The API has no visible authentication

- **Priority:** Medium — it exposes inventory to any caller, but the single route is read-only
- **Lens:** Security
- **Evidence:** `api/app.py:7`, `sec-02`
- **Scenario:** `GET /items` is public and no authentication or authorization marker appears anywhere in the API's code. If the service is reachable beyond a trusted network, anyone can read the inventory, and every route added later starts unauthenticated.
- **Fix:** Decide who may call the API. Put a shared dependency in front of the router now, even a minimal API-key check, so new routes inherit it.
- **Tradeoff:** Callers must send credentials, and the check is one more thing to test.
- **Confidence:** Low — this rests on a marker search; a gateway in front of the API could already provide authentication, and none is documented

### F5: Two services share one database and nothing owns its schema

- **Priority:** Medium — latent today because no code queries yet, but the design guarantees coupling once it does
- **Lens:** Data
- **Evidence:** `docker-compose.yml:2`, `docker-compose.yml:6`, `api/models.py:5`, `dat-02`, `dat-01`
- **Scenario:** The API and the worker get the same `DATABASE_URL`, and the only model definition lives in the API with no migration tool. When the API changes `Item`, the worker's queries break or silently read stale columns, and there is no migration history to say which schema a deployment expects.
- **Fix:** Name the API the owner of the schema. Add Alembic to the API and have the worker call the API or consume events instead of querying the tables, or give the worker its own schema.
- **Tradeoff:** Calling the API adds latency and an availability dependency. A separate schema duplicates data that must be kept in sync.
- **Confidence:** Medium — the shared URL and missing migrations are certain, but no code reads the database yet, so the harm is projected

### F6: Compose has no startup ordering, health checks or database volume

- **Priority:** Medium — it causes flaky starts and data loss on recreate, not a breach
- **Lens:** Infrastructure
- **Evidence:** `docker-compose.yml:2`, `docker-compose.yml:10`, `inf-01`
- **Scenario:** The API and worker start without waiting for `db`, so the first connection attempt can fail. No service reports health, so an orchestrator cannot tell a stuck container from a working one, and the `postgres:16` service has no volume, so recreating the container deletes the data.
- **Fix:** Add a `healthcheck` to `db` and `depends_on` with `condition: service_healthy` to the others, add a `HEALTHCHECK` to each Dockerfile, and mount a named volume at the Postgres data directory.
- **Tradeoff:** Slower, more deliberate startup, and a volume to manage and back up.
- **Confidence:** Medium — this assumes compose is the real deployment; if it is a development file only, the volume point matters less

### F7: The worker container runs as root

- **Priority:** Low — it needs another flaw to matter, and the worker handles little today
- **Lens:** Security
- **Evidence:** `worker/Dockerfile:1`, `sec-03`
- **Scenario:** The final stage never sets `USER`, so Celery runs as root in the container. A vulnerability in the worker or in a task's input would give an attacker root inside the container, which makes a container escape easier.
- **Fix:** Create an unprivileged user in the Dockerfile and switch to it before `CMD`.
- **Tradeoff:** File ownership and writable paths in the image may need adjusting.
- **Confidence:** High — the Dockerfile has no `USER` line

## Action plan

| Order | Action | Findings | Effort |
|---|---|---|---|
| 1 | Make the worker start: drop the `api` imports and configure the broker | F1, F2 | hours |
| 2 | Remove the committed password and the code default, then rotate it | F3 | hours |
| 3 | Add health checks, startup ordering and a database volume | F6 | hours |
| 4 | Decide who owns the schema and add migrations | F5 | days |
| 5 | Put authentication in front of the API | F4 | days |
| 6 | Run the worker as a non-root user | F7 | hours |

## What I inspected and what I did not

I read every source and config file in this small repository, the c4 facts, and the evidence signals. All seven signals held up; the two I rated as lower confidence (no authentication marker, no health check) are reported as such. F2 and the missing volume in F6 came from reading the compose file and the code, not from a signal. This review is static: I did not run the containers, so F1 and F2 are inferred from the build context and the addresses and have not been seen to fail. I cannot see production configuration, a gateway in front of the API, or any secret store, and the c4 facts hold no model of the broker.

## Report Metadata

- Generated By: architecture-skills plugin, architecture-review skill
- Generator Version: 3.6.0
- Source: https://github.com/ythalorossy/architecture-skills
