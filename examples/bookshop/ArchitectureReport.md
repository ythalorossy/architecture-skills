# Architecture Report

## Repository Information

**Repository Name:** bookshop

**Technology Stack:**

- Node.js
- Python
- React

---

## Executive Summary

[//]: # (summary:start)

Online shop where readers find books and buy them.

The model of Bookshop describes 2 containers, 2 data stores, 1 external system, 1 person, 5 relationships and 1 key flow.

[//]: # (summary:end)

The automated dependency checks found no structural concerns.

---

[//]: # (c4:start)

## Architecture overview

Bookshop sells books online. A React web app calls a FastAPI service, which keeps orders in its own PostgreSQL database, searches a catalogue index that the catalogue team runs, and charges cards through an external payment provider.

### Findings

- The card is charged before the order is stored (`api/bookshop/orders/service.py:31-32`): if the insert fails, the reader has paid and no order exists.
- The charge is sent without an idempotency key (`api/bookshop/payments/client.py:10`), so a retried request can charge the card twice.
- Search goes straight to another team's index (`api/bookshop/search/index.py:13`), with no fallback when it is unavailable.

### Recommendations

- Store the order as pending before charging, then mark it paid; refund when the update fails.
- Send an idempotency key with each charge so the request can be retried safely.

## Architecture (C4 model)

Online shop where readers find books and buy them

### Diagram key

What the shapes and lines in the diagrams below mean.

| Symbol | Meaning |
|---|---|
| Dark blue rounded box | **Person** — a user or a role outside the system. |
| Blue box (Level 1) | **Software system** — the system this report describes. |
| Blue box | **Container** — an application or service that runs on its own. |
| Blue cylinder | **Data store** — a database, cache or queue. |
| Light blue box | **Component** — a module, package or namespace inside one container. |
| Grey box | **External system** — run by someone else. |
| Dashed grey outline | The system or the container the diagram is about. |
| Solid arrow | A dependency or a call, labelled with what it does and the technology it uses. |

### Level 1: System context

![c4-context](c4-context.svg)

<details>
<summary>Mermaid source</summary>

```mermaid
---
title: "Bookshop · System context"
---
flowchart TB
    reader("Reader<br/>[Person]<br/>Searches the catalogue and buys<br/>books")
    system["Bookshop<br/>[Software System]<br/>Online shop where readers find<br/>books and buy them"]
    ext_payments_example["Payment provider<br/>[Software System]<br/>Charges the reader's card for an<br/>order"]
    db_elasticsearch["Catalogue index<br/>[Software System]<br/>Book catalogue search index, run<br/>and filled by the catalogue team"]
    reader -->|"Finds and buys books using<br/>[HTTPS]"| system
    system -->|"Searches the catalogue in<br/>[Elasticsearch client]"| db_elasticsearch
    system -->|"Charges cards with<br/>[HTTPS, httpx]"| ext_payments_example
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class reader person
    class system system
    class ext_payments_example,db_elasticsearch external
```

</details>

### Level 2: Containers

![c4-container](c4-container.svg)

<details>
<summary>Mermaid source</summary>

```mermaid
---
title: "Bookshop · Containers"
---
flowchart TB
    reader("Reader<br/>[Person]<br/>Searches the catalogue and buys<br/>books")
    subgraph boundary["Bookshop [Software System]"]
        bookshop_web["Web app<br/>[Container: React, Vite]<br/>Search and checkout pages in the<br/>browser"]
        bookshop_api["Bookshop API<br/>[Container: Python, FastAPI]<br/>Searches the catalogue and places<br/>orders"]
        db_postgresql[("Orders database<br/>[Container: PostgreSQL 16]<br/>Orders and their payment<br/>references")]
    end
    db_elasticsearch["Catalogue index<br/>[Software System]<br/>Book catalogue search index, run<br/>and filled by the catalogue team"]
    ext_payments_example["Payment provider<br/>[Software System]<br/>Charges the reader's card for an<br/>order"]
    reader -->|"Finds and buys books using<br/>[HTTPS]"| bookshop_web
    bookshop_web -->|"Searches books and places<br/>orders through<br/>[JSON/HTTPS]"| bookshop_api
    bookshop_api -->|"Stores orders in<br/>[psycopg]"| db_postgresql
    bookshop_api -->|"Searches the catalogue in<br/>[Elasticsearch client]"| db_elasticsearch
    bookshop_api -->|"Charges cards with<br/>[HTTPS, httpx]"| ext_payments_example
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class reader person
    class bookshop_web,bookshop_api,db_postgresql container
    class db_elasticsearch,ext_payments_example external
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

</details>

| Container | Technology | Responsibility | Code |
|---|---|---|---|
| **Web app** (container) | React, Vite | Search and checkout pages in the browser | `web` |
| **Bookshop API** (container) | Python, FastAPI | Searches the catalogue and places orders | `api` |
| **Orders database** (data store) | PostgreSQL 16 | Orders and their payment references | — |
| **Catalogue index** (data store) | Elasticsearch | Book catalogue search index, run and filled by the catalogue team | — |

### Level 3: Components

For each container: the modules it is built from (when it has several), then the code structure inside them (packages or namespaces and the imports between them).

#### Bookshop API

![c4-component-bookshop-api](c4-component-bookshop-api.svg)

<details>
<summary>Mermaid source</summary>

```mermaid
---
title: "Bookshop API"
---
flowchart TB
    subgraph boundary["Bookshop API [Container]"]
        bookshop_main["main<br/>[Component]<br/>HTTP routes; hand each request to<br/>a service"]
        bookshop_orders["orders<br/>[Component]<br/>Places an order: takes payment,<br/>then records it"]
        bookshop_payments["payments<br/>[Component]<br/>Client for the payment provider's<br/>charges API"]
        bookshop_search["search<br/>[Component]<br/>Full-text book search against the<br/>catalogue index"]
    end
    bookshop_main --> bookshop_orders
    bookshop_main --> bookshop_search
    bookshop_orders --> bookshop_payments
    db_elasticsearch[("Catalogue index<br/>[Container: Elasticsearch]<br/>Book catalogue search index, run<br/>and filled by the catalogue team")]
    bookshop_search -->|"Searches the catalogue in<br/>[Elasticsearch client]"| db_elasticsearch
    db_postgresql[("Orders database<br/>[Container: PostgreSQL 16]<br/>Orders and their payment<br/>references")]
    bookshop_orders -->|"Stores orders in<br/>[psycopg]"| db_postgresql
    ext_payments_example["Payment provider<br/>[Software System]<br/>Charges the reader's card for an<br/>order"]
    bookshop_payments -->|"Charges cards with<br/>[HTTPS, httpx]"| ext_payments_example
    bookshop_web["Web app<br/>[Container: React, Vite]<br/>Search and checkout pages in the<br/>browser"]
    bookshop_web -->|"Searches books and places<br/>orders through<br/>[JSON/HTTPS]"| boundary
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class bookshop_main,bookshop_orders,bookshop_payments,bookshop_search component
    class db_elasticsearch,db_postgresql,bookshop_web container
    class ext_payments_example external
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

</details>

#### Web app

![c4-component-bookshop-web](c4-component-bookshop-web.svg)

<details>
<summary>Mermaid source</summary>

```mermaid
---
title: "Web app"
---
flowchart TB
    subgraph boundary["Web app [Container]"]
        web_src__files["src (root files)<br/>[Component]"]
        web_src_api["src/api<br/>[Component]<br/>Fetch wrappers for the API's book<br/>and order endpoints"]
    end
    web_src__files --> web_src_api
    reader("Reader<br/>[Person]<br/>Searches the catalogue and buys<br/>books")
    reader -->|"Finds and buys books using<br/>[HTTPS]"| boundary
    bookshop_api["Bookshop API<br/>[Container: Python, FastAPI]<br/>Searches the catalogue and places<br/>orders"]
    boundary -->|"Searches books and places<br/>orders through<br/>[JSON/HTTPS]"| bookshop_api
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class web_src__files,web_src_api component
    class reader person
    class bookshop_api container
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

</details>

### Level 4: Code

The classes and interfaces of the key components: inheritance, implemented interfaces, dependencies inside the component and public methods. Boxes marked external live in another component.

#### Bookshop API · bookshop.orders

Order placement: payment first, then the order row

> Sources: OrderService → `api/bookshop/orders/service.py:23`, OrderRepository → `api/bookshop/orders/service.py:8`

![c4-code-bookshop-api-bookshop-orders](c4-code-bookshop-api-bookshop-orders.svg)

<details>
<summary>Mermaid source</summary>

```mermaid
---
title: "Bookshop API · bookshop.orders"
config:
  class:
    hideEmptyMembersBox: true
---
classDiagram
    direction TB
    class OrderService {
        +place(book_id, quantity, card_token) dict
    }
    class OrderRepository {
        +save(book_id, quantity, charge_id) int
    }
    OrderService ..> OrderRepository
    style OrderService fill:#85bbf0,stroke:#5d82a8,color:#000000
    style OrderRepository fill:#85bbf0,stroke:#5d82a8,color:#000000
```

</details>

### Key flows

How a request moves through the system, step by step.

#### Reader buys a book

From the Buy button to the stored, paid order.

![c4-flow-place-order](c4-flow-place-order.svg)

<details>
<summary>Mermaid source</summary>

```mermaid
---
title: "Reader buys a book"
---
sequenceDiagram
    actor reader as Reader
    participant bookshop_web as Web app
    participant web_src_api as web/src/api
    participant bookshop_main as bookshop.main
    participant bookshop_orders as bookshop.orders
    participant ext_payments_example as Payment provider
    participant db_postgresql as Orders database
    reader->>bookshop_web: Clicks Buy on a book
    web_src_api->>bookshop_main: POST /api/orders [JSON/HTTPS]
    bookshop_main->>bookshop_orders: Places the order
    bookshop_orders->>ext_payments_example: POST /v1/charges [HTTPS]
    bookshop_orders->>db_postgresql: Inserts the order with its charge id [psycopg]
    bookshop_main-->>web_src_api: Order id and charge id
```

</details>

### Deployment

#### docker compose

![c4-deployment](c4-deployment.svg)

<details>
<summary>Mermaid source</summary>

```mermaid
---
title: "Bookshop · Deployment (docker compose)"
---
flowchart TB
    subgraph host["Docker host [docker compose]"]
        svc_db[("db<br/>[Container instance]<br/>postgres:16")]
        svc_api["api (Bookshop API)<br/>[Container instance]<br/>build ./api<br/>ports 8000:8000"]
        svc_web["web (Web app)<br/>[Container instance]<br/>build ./web<br/>ports 5173:5173"]
    end
    svc_api -->|"depends on"| svc_db
    svc_web -->|"depends on"| svc_api
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class svc_db,svc_api,svc_web container
    style host fill:none,stroke:#444444,stroke-dasharray:6 4
```

</details>

No CI pipeline or hosting configuration was found in the repository.

### API endpoints

2 HTTP route(s) declared in code.

**Bookshop API**

| Method | Path | Declared in |
|---|---|---|
| GET | `/api/books` | `api/bookshop/main.py:11` |
| POST | `/api/orders` | `api/bookshop/main.py:16` |

### Configuration

| Variable | Default | Used by | Declared in |
|---|---|---|---|
| `DATABASE_URL` | `postgresql://bookshop:***@db:5432/bookshop` | Bookshop API | `api/bookshop/orders/service.py:27`, `docker-compose.yml:9` |
| `PAYMENTS_URL` | `https://payments.example/v1` | — | `docker-compose.yml:9` |
| `POSTGRES_DB` | `bookshop` | — | `docker-compose.yml:2` |
| `POSTGRES_PASSWORD` | — | — | `docker-compose.yml:2` |
| `POSTGRES_USER` | `bookshop` | — | `docker-compose.yml:2` |
| `SEARCH_URL` | `https://search.catalog.example` | Bookshop API | `api/bookshop/search/index.py:10`, `docker-compose.yml:9` |

### Technology inventory

Runtime, frameworks and key libraries declared in each container's build files.

| Container | Declared |
|---|---|
| **Bookshop API** | `Python >=3.11`, `fastapi>=0.110`, `uvicorn>=0.29`, `psycopg>=3.1`, `elasticsearch>=8.12`, `httpx>=0.27` |
| **Web app** | `react ^18.3.1`, `react-dom ^18.3.1`, `vite ^5.4.0` |

### Assumptions

Not backed by code evidence; confirm with the team:

- **Reader**: Searches the catalogue and buys books
- **reader → bookshop-web**: Finds and buys books using

### C4 files

- [c4-context.mmd](c4-context.mmd)
- [c4-container.mmd](c4-container.mmd)
- [c4-component-bookshop-api.mmd](c4-component-bookshop-api.mmd)
- [c4-component-bookshop-web.mmd](c4-component-bookshop-web.mmd)
- [c4-flow-place-order.mmd](c4-flow-place-order.mmd)
- [c4-code-bookshop-api-bookshop-orders.mmd](c4-code-bookshop-api-bookshop-orders.mmd)
- [c4-deployment.mmd](c4-deployment.mmd)
- [c4-facts.json](c4-facts.json)
- [c4-model.json](c4-model.json)

[//]: # (c4:end)

---

## Architectural Observations

### Strengths

[//]: # (strengths:start)

- Every container, data store and external system found in the code is in the model.
- Every container says what it is responsible for.
- The model names who the system is for: Reader.
- 1 key flow is written down end to end: Reader buys a book.
- Every container and external system points at the code that proves it.
- No circular project references.

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

**Project folders:** api, web

<details>
<summary>Full dependency graph</summary>

![Dependency graph](dependency-graph.svg)

```mermaid
---
title: "bookshop · Project dependency graph"
---
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

- [Diagram image (SVG)](dependency-graph.svg)
- C4 diagrams: listed under Architecture (C4 model) above
- [Mermaid source](dependency-graph.mmd)
- [Dependency data (JSON)](dependency-graph.json)
- [Repository scan (JSON)](repository-scan.json)
- [Summary (JSON)](summary.json)

---

## Report Metadata

Generator Version: 3.5.0

