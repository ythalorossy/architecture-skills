# Architecture Report

## Repository Information

**Repository Name:** bookshop

**Technology Stack:**

- Node.js
- Python
- React

---

## Executive Summary

bookshop has 6 projects (6 production, 0 test) with 4 project references between them. The analysis found no structural concerns.

---

[//]: # (c4:start)

## Architecture (C4 model)

> Drawn from code facts only: no `c4-model.json` yet, so people, external purposes, descriptions and key flows are missing and the System Context level is left out. Write `c4-model.json` and run `render_c4.py` to complete it.

### Level 2: Containers

```mermaid
flowchart TB
    subgraph boundary["`**bookshop** [Software System]`"]
        bookshop_api["`**bookshop-api**
[Container: Python, FastAPI]
web api`"]
        bookshop_web["`**bookshop-web**
[Container: React]
web app`"]
        db_elasticsearch[("`**Elasticsearch**
[Container: Elasticsearch]`")]
        db_postgresql[("`**PostgreSQL**
[Container: PostgreSQL]`")]
    end
    ext_covers_example["`**covers.example**
[Software System]`"]
    ext_payments_example["`**payments.example**
[Software System]`"]
    bookshop_api -->|"`Reads/writes`"| db_postgresql
    bookshop_web -->|"`Calls /api (dev-server proxy
to http://localhost:8000)
[HTTP]`"| bookshop_api
    bookshop_api -->|"`Reads/writes`"| db_elasticsearch
    bookshop_api -->|"`Calls`"| ext_covers_example
    bookshop_api -->|"`Calls`"| ext_payments_example
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class bookshop_api,bookshop_web,db_elasticsearch,db_postgresql container
    class ext_covers_example,ext_payments_example external
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

| Container | Technology | Responsibility | Code |
|---|---|---|---|
| **bookshop-api** (container) | Python, FastAPI | web api | `api` |
| **bookshop-web** (container) | React | web app | `web` |
| **Elasticsearch** (data store) | Elasticsearch | — | — |
| **PostgreSQL** (data store) | PostgreSQL | — | — |

### Level 3: Components

For each container: the modules it is built from (when it has several), then the code structure inside them (packages or namespaces and the imports between them).

#### bookshop-api

```mermaid
flowchart TB
    subgraph boundary["`**bookshop-api** [Container]`"]
        bookshop_main["`**main**
[Component]`"]
        bookshop_orders["`**orders**
[Component]`"]
        bookshop_payments["`**payments**
[Component]`"]
        bookshop_search["`**search**
[Component]`"]
    end
    bookshop_main --> bookshop_orders
    bookshop_main --> bookshop_search
    bookshop_orders --> bookshop_payments
    db_elasticsearch[("`**Elasticsearch**
[Container: Elasticsearch]`")]
    bookshop_search -->|"`Reads/writes`"| db_elasticsearch
    db_postgresql[("`**PostgreSQL**
[Container: PostgreSQL]`")]
    bookshop_orders -->|"`Reads/writes`"| db_postgresql
    ext_payments_example["`**payments.example**
[Software System]`"]
    bookshop_payments -->|"`Calls`"| ext_payments_example
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class bookshop_main,bookshop_orders,bookshop_payments,bookshop_search component
    class db_elasticsearch,db_postgresql container
    class ext_payments_example external
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

#### bookshop-web

```mermaid
flowchart TB
    subgraph boundary["`**bookshop-web** [Container]`"]
        web_src__files["`**src (root files)**
[Component]`"]
        web_src_api["`**src/api**
[Component]`"]
    end
    web_src__files --> web_src_api
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class web_src__files,web_src_api component
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

### Deployment

#### docker compose

```mermaid
flowchart TB
    subgraph host["`**Docker host** [docker compose]`"]
        svc_db[("`**db**
[Container instance]
postgres:16`")]
        svc_api["`**api (bookshop-api)**
[Container instance]
build ./api
ports 8000:8000`"]
        svc_web["`**web (bookshop-web)**
[Container instance]
build ./web
ports 5173:5173`"]
    end
    svc_api -->|"`depends on`"| svc_db
    svc_web -->|"`depends on`"| svc_api
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class svc_db,svc_api,svc_web container
    style host fill:none,stroke:#444444,stroke-dasharray:6 4
```

No CI pipeline or hosting configuration was found in the repository.

### API endpoints

2 HTTP route(s) declared in code.

**bookshop-api**

| Method | Path | Declared in |
|---|---|---|
| GET | `/api/books` | `api/bookshop/main.py:11` |
| POST | `/api/orders` | `api/bookshop/main.py:16` |

### Configuration

| Variable | Default | Used by | Declared in |
|---|---|---|---|
| `DATABASE_URL` | `postgresql://bookshop:***@db:5432/bookshop` | bookshop-api | `api/bookshop/orders/service.py:27`, `docker-compose.yml:9` |
| `PAYMENTS_URL` | `https://payments.example/v1` | — | `docker-compose.yml:9` |
| `POSTGRES_DB` | `bookshop` | — | `docker-compose.yml:2` |
| `POSTGRES_PASSWORD` | — | — | `docker-compose.yml:2` |
| `POSTGRES_USER` | `bookshop` | — | `docker-compose.yml:2` |
| `SEARCH_URL` | `https://search.catalog.example` | bookshop-api | `api/bookshop/search/index.py:10`, `docker-compose.yml:9` |

### Technology inventory

Runtime, frameworks and key libraries declared in each container's build files.

| Container | Declared |
|---|---|
| **bookshop-api** | `Python >=3.11`, `fastapi>=0.110`, `uvicorn>=0.29`, `psycopg>=3.1`, `elasticsearch>=8.12`, `httpx>=0.27` |
| **bookshop-web** | `react ^18.3.1`, `react-dom ^18.3.1`, `vite ^5.4.0` |

### C4 files

- [c4-container.mmd](c4-container.mmd)
- [c4-component-bookshop-api.mmd](c4-component-bookshop-api.mmd)
- [c4-component-bookshop-web.mmd](c4-component-bookshop-web.mmd)
- [c4-deployment.mmd](c4-deployment.mmd)
- [c4-facts.json](c4-facts.json)

[//]: # (c4:end)

---

## Architectural Observations

### Strengths

- No circular project references.
- Projects with no project references (the core that the rest builds on): bookshop.payments, bookshop.search, web/src/api.

### Concerns

No automated concerns detected.

---

## Recommendations

No changes recommended from the automated checks. Review the diagram for boundaries the checks cannot see.

---

## Appendix: Project Dependency Graph

Every project or module and every reference between them, tests included. The automated checks above (cycles, stray projects, untested projects) are based on this graph.

**Solutions / build roots:** none found

**Project folders:** api, web

<details>
<summary>Full dependency graph</summary>

```mermaid
graph TD
    web_src__files["web/src (files)"]
    subgraph group_api["api"]
        bookshop_main["bookshop.main"]
        bookshop_orders["bookshop.orders"]
        bookshop_payments["bookshop.payments"]
        bookshop_search["bookshop.search"]
    end
    subgraph group_web["web"]
        web_src_api["web/src/api"]
    end
    bookshop_main --> bookshop_orders
    bookshop_main --> bookshop_search
    bookshop_orders --> bookshop_payments
    web_src__files --> web_src_api
```

</details>

### Components

| Project | Ecosystem | Folder | Kind | Depends on | Used by |
|---|---|---|---|---|---|
| bookshop.main | Python | api | production | 2 | 0 |
| bookshop.orders | Python | api | production | 1 | 1 |
| bookshop.payments | Python | api | production | 0 | 1 |
| bookshop.search | Python | api | production | 0 | 1 |
| web/src (files) | Node.js | - | production | 1 | 0 |
| web/src/api | Node.js | web | production | 0 | 1 |

### Dependency Analysis

### bookshop.main
- depends on bookshop.orders
- depends on bookshop.search

### bookshop.orders
- depends on bookshop.payments
- used by bookshop.main

### bookshop.payments
- no project references
- used by bookshop.orders

### bookshop.search
- no project references
- used by bookshop.main

### web/src (files)
- depends on web/src/api

### web/src/api
- no project references
- used by web/src (files)

---

## Generated Artifacts

- C4 diagrams: listed under Architecture (C4 model) above
- [Mermaid source](dependency-graph.mmd)
- [Dependency data (JSON)](dependency-graph.json)
- [Repository scan (JSON)](repository-scan.json)
- [Summary (JSON)](summary.json)

---

## Report Metadata

Generator Version: <version>

