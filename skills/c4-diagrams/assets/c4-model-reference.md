<!-- Provenance rule: examples in this file come only from tests/fixtures/repos/. The JSON block below is a
copy of tests/fixtures/repos/bookshop/c4-model.json, a synthetic repository; tests/test_reference_example.py fails
if they differ, if the model stops validating against that fixture, or if an evidence path doesn't resolve there.
Never paste a model from another codebase here. -->

# c4-model.json reference

`c4-model.json`, written by the agent, holds the parts of the C4 model that need judgement: who uses the system, what each external system is for, and a one-line description of every element. `render_c4.py` draws the diagrams from it, combined with the facts in `c4-facts.json`.

## Shape

This is the complete model of Bookshop, a small synthetic sample system: a React web app, a Python API, the orders database it owns, a catalogue search index another team runs, and a payment provider. It covers every fact the analyzer finds in that sample, so it validates as it stands.

```json
{
  "system": {
    "name": "Bookshop",
    "description": "Online shop where readers find books and buy them"
  },
  "people": [
    {
      "id": "reader",
      "name": "Reader",
      "description": "Searches the catalogue and buys books",
      "assumption": true
    }
  ],
  "containers": [
    {
      "id": "bookshop-web",
      "name": "Web app",
      "technology": "React, Vite",
      "description": "Search and checkout pages in the browser",
      "evidence": [
        "web/package.json:11",
        "docker-compose.yml:20"
      ]
    },
    {
      "id": "bookshop-api",
      "name": "Bookshop API",
      "technology": "Python, FastAPI",
      "description": "Searches the catalogue and places orders",
      "evidence": [
        "api/bookshop/main.py:6",
        "docker-compose.yml:9"
      ]
    },
    {
      "id": "db-postgresql",
      "name": "Orders database",
      "technology": "PostgreSQL 16",
      "type": "database",
      "description": "Orders and their payment references",
      "evidence": [
        "api/bookshop/orders/service.py:15",
        "docker-compose.yml:3"
      ]
    },
    {
      "id": "db-elasticsearch",
      "name": "Catalogue index",
      "technology": "Elasticsearch",
      "type": "database",
      "external": true,
      "description": "Book catalogue search index, run and filled by the catalogue team",
      "evidence": [
        "api/bookshop/search/index.py:7",
        "docker-compose.yml:13"
      ]
    }
  ],
  "external_systems": [
    {
      "id": "ext-payments-example",
      "name": "Payment provider",
      "description": "Charges the reader's card for an order",
      "evidence": [
        "api/bookshop/payments/client.py:10"
      ]
    }
  ],
  "relationships": [
    {
      "from": "reader",
      "to": "bookshop-web",
      "description": "Finds and buys books using",
      "technology": "HTTPS",
      "assumption": true
    },
    {
      "from": "bookshop-web",
      "to": "bookshop-api",
      "description": "Searches books and places orders through",
      "technology": "JSON/HTTPS"
    },
    {
      "from": "bookshop-api",
      "to": "db-postgresql",
      "description": "Stores orders in",
      "technology": "psycopg"
    },
    {
      "from": "bookshop-api",
      "to": "db-elasticsearch",
      "description": "Searches the catalogue in",
      "technology": "Elasticsearch client"
    },
    {
      "from": "bookshop-api",
      "to": "ext-payments-example",
      "description": "Charges cards with",
      "technology": "HTTPS, httpx"
    }
  ],
  "components": {
    "bookshop-web": {
      "web/src/api": "Fetch wrappers for the API's book and order endpoints"
    },
    "bookshop-api": {
      "bookshop.main": "HTTP routes; hand each request to a service",
      "bookshop.orders": "Places an order: takes payment, then records it",
      "bookshop.payments": "Client for the payment provider's charges API",
      "bookshop.search": "Full-text book search against the catalogue index"
    }
  },
  "flows": [
    {
      "id": "place-order",
      "name": "Reader buys a book",
      "description": "From the Buy button to the stored, paid order.",
      "steps": [
        {
          "from": "reader",
          "to": "bookshop-web",
          "description": "Clicks Buy on a book",
          "evidence": [
            "web/src/main.tsx:15 (the Buy button)"
          ]
        },
        {
          "from": "web/src/api",
          "to": "bookshop.main",
          "description": "POST /api/orders",
          "technology": "JSON/HTTPS",
          "evidence": [
            "web/src/api/client.ts:12-18"
          ]
        },
        {
          "from": "bookshop.main",
          "to": "bookshop.orders",
          "description": "Places the order",
          "evidence": [
            "api/bookshop/main.py:16-18"
          ]
        },
        {
          "from": "bookshop.orders",
          "to": "ext-payments-example",
          "description": "POST /v1/charges",
          "technology": "HTTPS",
          "evidence": [
            "api/bookshop/payments/client.py:9-12"
          ]
        },
        {
          "from": "bookshop.orders",
          "to": "db-postgresql",
          "description": "Inserts the order with its charge id",
          "technology": "psycopg",
          "evidence": [
            "api/bookshop/orders/service.py:14-20"
          ]
        },
        {
          "from": "bookshop.main",
          "to": "web/src/api",
          "description": "Order id and charge id",
          "reply": true,
          "evidence": [
            "api/bookshop/orders/service.py:30-33"
          ]
        }
      ]
    }
  ],
  "code": [
    {
      "container": "bookshop-api",
      "component": "bookshop.orders",
      "description": "Order placement: payment first, then the order row",
      "types": [
        "OrderService"
      ]
    }
  ],
  "excluded": [
    {
      "id": "ext-covers-example",
      "reason": "Called only by a one-off import script run by hand, not by the running system"
    }
  ],
  "summary": {
    "overview": "Bookshop sells books online. A React web app calls a FastAPI service, which keeps orders in its own PostgreSQL database, searches a catalogue index that the catalogue team runs, and charges cards through an external payment provider.",
    "findings": [
      "The card is charged before the order is stored (`api/bookshop/orders/service.py:31-32`): if the insert fails, the reader has paid and no order exists.",
      "The charge is sent without an idempotency key (`api/bookshop/payments/client.py:10`), so a retried request can charge the card twice.",
      "Search goes straight to another team's index (`api/bookshop/search/index.py:13`), with no fallback when it is unavailable."
    ],
    "recommendations": [
      "Store the order as pending before charging, then mark it paid; refund when the update fails.",
      "Send an idempotency key with each charge so the request can be retried safely."
    ]
  }
}
```

## Rules

- **Cover every fact.** Every `id` in `c4-facts.json` (`containers`, `data_stores`, `external_systems`) must appear in the model: as an element with the same `id`, in some element's `facts` list (to merge or rename facts), or in `excluded` with a reason. A fact you missed is drift: `render_c4.py` prints a `DRIFT:` line for it and exits 0 (exit 2 with `--strict`).
- **Data stores are containers.** Put a database, cache or queue the system owns in `containers` with `"type": "database"` (or `"queue"`). A store the system doesn't own (a SaaS vector DB, another team's database) goes there too, with `"external": true`; it is then drawn outside the system boundary.
- **Evidence or assumption.** Give each person, container and external system — and each flow or flow step — `evidence` (repo-relative `file` or `file:line`), or mark it `"assumption": true`. A flow is read out of the code rather than found in it, so say which steps you traced and which you inferred. Assumptions are listed in the report for the team to confirm. People are usually assumptions unless the code names them (auth roles, UI copy, README).
- **Don't invent.** Only add elements and relationships the code, config or docs support. When you have no evidence for who calls the API, say so with one `assumption` person rather than inventing several.
- **Relationship text** reads from → to: "Stores orders in", "Charges cards with". `technology` is the protocol or library (HTTPS, gRPC, EF Core, SQS).
- **`components`** gives a one-line description per component, keyed by container id and then a component id from `c4-facts.json`: a module (`containers[].components.nodes`) or a package/namespace inside one (`containers[].code_components.nodes`, ids like `module::package`). Describe the important ones; the nodes and edges themselves come from the code and can't be changed in the model.
- **`flows`** are the key request paths, drawn as sequence diagrams. Each has an `id`, a `name`, an optional `description` and ordered `steps`. A step's `from`/`to` is a person, container or external system id, or a component id (module or `module::package`) when the step happens inside a container. Optional per step: `technology`, `"reply": true` (dashed return arrow), `"async": true`, `note`, and — as for any element — `evidence` or `"assumption": true`. A flow takes both too, covering every step that carries neither. A step nothing backs is drawn with `(?)` after its text and listed under Assumptions. Trace real code paths: 1–3 flows of 4–10 steps each, starting from an endpoint, UI action, CLI command or scheduled job you can point to.
- **`code`** (Level 4) lists the 2–5 key components to draw as class diagrams. Each entry has `container` (a model container id), `component` (a module or `module::package` id from `c4-facts.json`), an optional `description`, and optional `types` to center the diagram on (they are drawn with their direct neighbours). Without `types` the most connected types are drawn, at most 12. Type names must exist in that component's code: `render_c4.py` fails and suggests close names otherwise. Pick components with behaviour, not model or DTO folders.
- **`summary`** is your own analysis, written into `ArchitectureReport.md` as an "Architecture overview" right after the Executive Summary: an `overview` paragraph (what the system does and how it is built), `findings` (what matters for the team: risks, coupling, missing pieces, each with a `file:line`), and `recommendations` (each backed by a finding). All three are optional; leave out what you have nothing evidence-based to say about.
- **Ids** are short kebab-case strings, unique across people, containers and external systems. Keep fact ids as they are so re-runs line up.

## Re-running

`analyze_repository.py` never overwrites `c4-model.json`. When the code changes, the facts are refreshed:

Every model is checked in three tiers:

- **`ok`**: the model is well-formed and covers every fact. It is drawn as written.
- **`drift`**: the model is well-formed but some facts are not covered yet (a container found in the code and not in the model). The model is drawn with the new facts listed in an `### Unreviewed facts` section of the report, one `DRIFT:` line per item on stdout, and `c4.model_status == "drift"` in `summary.json`. `render_c4.py` exits 0; with `--strict` it exits 2.
- **`invalid`**: the model cannot be drawn as written. This covers a JSON syntax error (the message names the line and column, e.g. `c4-model.json: line 3, column 1: trailing comma before closing bracket`), a wrong-typed section or element (the message gives the JSON path, e.g. `containers[3]`), an unknown relationship or flow id, and duplicate ids. The facts-only diagrams are drawn instead and the errors are listed in `c4.model_errors[]`. `render_c4.py` exits 1.

`analyze_repository.py` never aborts on a bad model: it records the tier in `summary.json` and exits 0.

When you re-run `render_c4.py` after a change to the code or the model, fix every error, resolve every drift item (add the fact to the model, or list it in `excluded` with a reason), and fix or justify each warning. A warning does not change the exit code.

In all cases `c4-model.json` is left unchanged by the analyzer.

```bash
python3 scripts/render_c4.py <output folder>
```

(`scripts/` is relative to the skill folder.)
