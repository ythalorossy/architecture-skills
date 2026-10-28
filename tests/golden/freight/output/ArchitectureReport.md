# Architecture Report

## Repository Information

**Repository Name:** freight

**Technology Stack:**

- Node.js
- Python

---

## Executive Summary

[//]: # (summary:start)

freight has 5 projects (5 production, 0 tests) with 3 project references between them.

[//]: # (summary:end)

The automated dependency checks found no structural concerns.

---

[//]: # (c4:start)

## Architecture (C4 model)

> Drawn from code facts only: no `c4-model.json` yet, so people, external purposes, descriptions and key flows are missing and the System Context level is left out. Write `c4-model.json` and run `render_c4.py` to complete it.

### Diagram key

What the shapes and lines in the diagrams below mean.

| Symbol | Meaning |
|---|---|
| Blue box | **Container** — an application or service that runs on its own. |
| Blue cylinder | **Data store** — a database, cache or queue. |
| Light blue box | **Component** — a module, package or namespace inside one container. |
| Dashed grey outline | The system or the container the diagram is about. |
| Solid arrow | A dependency or a call, labelled with what it does and the technology it uses. |

### Level 2: Containers

```mermaid
---
title: "freight · Containers"
---
flowchart TB
    subgraph boundary["freight [Software System]"]
        freight_api["freight-api<br/>[Container: Python, FastAPI]<br/>web api"]
        freight_worker["freight-worker<br/>[Container: Node.js, CLI]<br/>cli"]
        adminer["adminer<br/>[Container: adminer:4]<br/>service"]
        db_postgresql[("PostgreSQL<br/>[Container: PostgreSQL]")]
        db_redis[("Redis<br/>[Container: Redis]")]
    end
    freight_api -->|"Reads/writes"| db_postgresql
    freight_worker -->|"Reads/writes"| db_postgresql
    adminer -->|"Depends on"| db_postgresql
    freight_api -->|"Reads/writes"| db_redis
    freight_worker -->|"Reads/writes"| db_redis
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class freight_api,freight_worker,adminer,db_postgresql,db_redis container
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

| Container | Technology | Responsibility | Code |
|---|---|---|---|
| **freight-api** (container) | Python, FastAPI | web api | `api` |
| **freight-worker** (container) | Node.js, CLI | cli | `worker` |
| **adminer** (container) | adminer:4 | service | — |
| **PostgreSQL** (data store) | PostgreSQL | — | — |
| **Redis** (data store) | Redis | — | — |

### Level 3: Components

For each container: the modules it is built from (when it has several), then the code structure inside them (packages or namespaces and the imports between them).

#### freight-api

```mermaid
---
title: "freight-api"
---
flowchart TB
    subgraph boundary["freight-api [Container]"]
        freight_main["main<br/>[Component]"]
        freight_storage["storage<br/>[Component]"]
        freight_tracking["tracking<br/>[Component]"]
    end
    freight_main --> freight_tracking
    freight_tracking --> freight_storage
    db_postgresql[("PostgreSQL<br/>[Container: PostgreSQL]")]
    freight_tracking -->|"Reads/writes"| db_postgresql
    db_redis[("Redis<br/>[Container: Redis]")]
    freight_storage -->|"Reads/writes"| db_redis
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class freight_main,freight_storage,freight_tracking component
    class db_postgresql,db_redis container
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

#### freight-worker

```mermaid
---
title: "freight-worker"
---
flowchart TB
    subgraph boundary["freight-worker [Container]"]
        freight_shared["@freight/shared<br/>[Component]"]
        freight_worker["freight-worker<br/>[Component]"]
    end
    freight_worker --> freight_shared
    db_postgresql[("PostgreSQL<br/>[Container: PostgreSQL]")]
    freight_worker -->|"Reads/writes"| db_postgresql
    db_redis[("Redis<br/>[Container: Redis]")]
    freight_shared -->|"Reads/writes"| db_redis
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class freight_shared,freight_worker component
    class db_postgresql,db_redis container
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

### Deployment

#### docker compose

```mermaid
---
title: "freight · Deployment (docker compose)"
---
flowchart TB
    subgraph host["Docker host [docker compose]"]
        svc_db[("db<br/>[Container instance]<br/>postgres:16")]
        svc_api["api (freight-api)<br/>[Container instance]<br/>build ./api<br/>ports 8080:8080"]
        svc_worker["worker (freight-worker)<br/>[Container instance]<br/>build ./worker"]
        svc_adminer["adminer<br/>[Container instance]<br/>adminer:4<br/>ports 8081:8080"]
    end
    svc_api -->|"depends on"| svc_db
    svc_worker -->|"depends on"| svc_db
    svc_adminer -->|"depends on"| svc_db
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class svc_db,svc_api,svc_worker,svc_adminer container
    style host fill:none,stroke:#444444,stroke-dasharray:6 4
```

No CI pipeline or hosting configuration was found in the repository.

### API endpoints

2 HTTP route(s) declared in code.

**freight-api**

| Method | Path | Declared in |
|---|---|---|
| GET | `/api/shipments` | `api/freight/main.py:14` |
| GET | `/api/shipments/{reference}` | `api/freight/main.py:9` |

### Configuration

| Variable | Default | Used by | Declared in |
|---|---|---|---|
| `CACHE_URL` | `redis://cache.freight.example:6379/0` | freight-api, freight-worker | `api/freight/storage/cache.py:14`, `shared/src/cache.ts:8`, `docker-compose.yml:9` |
| `CARRIER_API_URL` | `https://api.carrier.example/v3` | freight-worker | `worker/src/carriers.ts:9`, `docker-compose.yml:19` |
| `DATABASE_URL` | `postgresql://freight:***@db:5432/freight` | freight-api, freight-worker | `api/freight/tracking/service.py:38`, `worker/src/shipments.ts:9`, `docker-compose.yml:9` |
| `POLL_SECONDS` | `60` | freight-worker | `worker/src/poller.ts:6`, `docker-compose.yml:19` |
| `POSTGRES_DB` | `freight` | — | `docker-compose.yml:2` |
| `POSTGRES_PASSWORD` | — | — | `docker-compose.yml:2` |
| `POSTGRES_USER` | `freight` | — | `docker-compose.yml:2` |

### Technology inventory

Runtime, frameworks and key libraries declared in each container's build files.

| Container | Declared |
|---|---|
| **freight-api** | `Python >=3.11`, `fastapi>=0.110`, `uvicorn>=0.29`, `psycopg>=3.1`, `redis>=5.0` |
| **freight-worker** | `redis ^4.7.0`, `typescript ^5.5.4`, `@freight/shared file:../shared`, `pg ^8.12.0` |
| **adminer** | `adminer:4` |

### C4 files

- [c4-container.mmd](c4-container.mmd)
- [c4-component-freight-api.mmd](c4-component-freight-api.mmd)
- [c4-component-freight-worker.mmd](c4-component-freight-worker.mmd)
- [c4-deployment.mmd](c4-deployment.mmd)
- [c4-facts.json](c4-facts.json)

[//]: # (c4:end)

---

## Architectural Observations

### Strengths

[//]: # (strengths:start)

- No circular project references.
- Projects with no project references (the core that the rest builds on): @freight/shared, freight.storage.

[//]: # (strengths:end)

### Concerns

No automated concerns detected.

---

## Recommendations

No changes recommended from the automated checks. Review the diagram for boundaries the checks cannot see.

---

## Appendix: Project Dependency Graph

Every project or module and every reference between them, tests included. The automated checks above (cycles, stray projects, untested projects) are based on this graph.

**Solutions / build roots:** none found

**Project folders:** api

<details>
<summary>Full dependency graph</summary>

```mermaid
---
title: "freight · Project dependency graph"
---
graph TD
    freight_shared["@freight/shared"]
    freight_worker["freight-worker"]
    subgraph group_api["api"]
        freight_main["freight.main"]
        freight_storage["freight.storage"]
        freight_tracking["freight.tracking"]
    end
    freight_worker --> freight_shared
    freight_main --> freight_tracking
    freight_tracking --> freight_storage
```

</details>

### Components

| Project | Ecosystem | Folder | Kind | Depends on | Used by |
|---|---|---|---|---|---|
| @freight/shared | Node.js | - | production | 0 | 1 |
| freight-worker | Node.js | - | production | 1 | 0 |
| freight.main | Python | api | production | 1 | 0 |
| freight.storage | Python | api | production | 0 | 1 |
| freight.tracking | Python | api | production | 1 | 1 |

### Dependency Analysis

### @freight/shared
- no project references
- used by freight-worker

### freight-worker
- depends on @freight/shared

### freight.main
- depends on freight.tracking

### freight.storage
- no project references
- used by freight.tracking

### freight.tracking
- depends on freight.storage
- used by freight.main

---

## Generated Artifacts

- C4 diagrams: listed under Architecture (C4 model) above
- [Mermaid source](dependency-graph.mmd)
- [Dependency data (JSON)](dependency-graph.json)
- [Repository scan (JSON)](repository-scan.json)
- [Summary (JSON)](summary.json)

---

## Report Metadata

- Generated By: architecture-skills plugin, c4-diagrams skill
- Generator Version: <version>
- Source: https://github.com/ythalorossy/architecture-skills

