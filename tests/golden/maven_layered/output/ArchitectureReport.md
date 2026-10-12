# Architecture Report

## Repository Information

**Repository Name:** maven_layered

**Technology Stack:**

- Java

---

## Executive Summary

maven_layered has 4 projects (4 production, 0 test) with 4 project references between them. The analysis found no structural concerns.

---

[//]: # (c4:start)

## Architecture (C4 model)

> Drawn from code facts only: no `c4-model.json` yet, so people, external purposes, descriptions and key flows are missing and the System Context level is left out. Write `c4-model.json` and run `render_c4.py` to complete it.

### Level 2: Containers

```mermaid
flowchart TB
    subgraph boundary["maven_layered [Software System]"]
        shop_api["shop-api<br/>[Container: Spring Boot]<br/>web api"]
        db_redis[("Redis<br/>[Container: Redis]")]
    end
    shop_api -->|"Reads/writes"| db_redis
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class shop_api,db_redis container
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

| Container | Technology | Responsibility | Code |
|---|---|---|---|
| **shop-api** (container) | Spring Boot | web api | `backend/shop-api` |
| **Redis** (data store) | Redis | — | — |

### Level 3: Components

For each container: the modules it is built from (when it has several), then the code structure inside them (packages or namespaces and the imports between them).

#### shop-api

```mermaid
flowchart TB
    subgraph boundary["shop-api [Container]"]
        shop_api["shop-api<br/>[Component]"]
        shop_application["shop-application<br/>[Component]"]
        shop_domain["shop-domain<br/>[Component]"]
        shop_infrastructure["shop-infrastructure<br/>[Component]"]
    end
    shop_api --> shop_application
    shop_api --> shop_infrastructure
    shop_application --> shop_domain
    shop_infrastructure --> shop_application
    db_redis[("Redis<br/>[Container: Redis]")]
    shop_infrastructure -->|"Reads/writes"| db_redis
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class shop_api,shop_application,shop_domain,shop_infrastructure component
    class db_redis container
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

#### shop-api · code structure

```mermaid
flowchart TB
    subgraph boundary["shop-api · code structure [Container]"]
        subgraph module_shop_api["shop-api"]
            shop_api__api["api<br/>[Component]"]
        end
        subgraph module_shop_application["shop-application"]
            shop_application__application["application<br/>[Component]"]
        end
        subgraph module_shop_domain["shop-domain"]
            shop_domain__domain["domain<br/>[Component]"]
        end
        subgraph module_shop_infrastructure["shop-infrastructure"]
            shop_infrastructure__infrastructure["infrastructure<br/>[Component]"]
        end
    end
    shop_api__api --> shop_application__application
    shop_application__application --> shop_domain__domain
    shop_infrastructure__infrastructure --> shop_domain__domain
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class shop_api__api,shop_application__application,shop_domain__domain,shop_infrastructure__infrastructure component
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
    style module_shop_api fill:#f4f8fc,stroke:#9fb6cc
    style module_shop_application fill:#f4f8fc,stroke:#9fb6cc
    style module_shop_domain fill:#f4f8fc,stroke:#9fb6cc
    style module_shop_infrastructure fill:#f4f8fc,stroke:#9fb6cc
```

### API endpoints

1 HTTP route(s) declared in code.

**shop-api**

| Method | Path | Declared in |
|---|---|---|
| POST | `/orders` | `backend/shop-api/src/main/java/com/example/shop/api/OrderController.java:11` |

### Technology inventory

Runtime, frameworks and key libraries declared in each container's build files.

| Container | Declared |
|---|---|
| **shop-api** | `spring-boot-starter-web`, `spring-boot-starter-data-redis` |

### C4 files

- [c4-container.mmd](c4-container.mmd)
- [c4-component-shop-api.mmd](c4-component-shop-api.mmd)
- [c4-structure-shop-api.mmd](c4-structure-shop-api.mmd)
- [c4-facts.json](c4-facts.json)

[//]: # (c4:end)

---

## Architectural Observations

### Strengths

- No circular project references.
- Projects with no project references (the core that the rest builds on): shop-domain.
- Every project is listed in a solution, workspace or aggregator build.

### Concerns

No automated concerns detected.

---

## Recommendations

No changes recommended from the automated checks. Review the diagram for boundaries the checks cannot see.

---

## Appendix: Project Dependency Graph

Every project or module and every reference between them, tests included. The automated checks above (cycles, stray projects, untested projects) are based on this graph.

**Solutions / build roots:** backend/pom.xml

**Project folders:** backend

<details>
<summary>Full dependency graph</summary>

```mermaid
graph TD
    subgraph group_backend["backend"]
        shop_api["shop-api"]
        shop_application["shop-application"]
        shop_domain["shop-domain"]
        shop_infrastructure["shop-infrastructure"]
    end
    shop_api --> shop_application
    shop_api --> shop_infrastructure
    shop_application --> shop_domain
    shop_infrastructure --> shop_application
```

</details>

### Components

| Project | Ecosystem | Folder | Kind | Depends on | Used by |
|---|---|---|---|---|---|
| shop-api | Java (Maven) | backend | production | 2 | 0 |
| shop-application | Java (Maven) | backend | production | 1 | 2 |
| shop-domain | Java (Maven) | backend | production | 0 | 1 |
| shop-infrastructure | Java (Maven) | backend | production | 1 | 1 |

### Dependency Analysis

### shop-api
- depends on shop-application
- depends on shop-infrastructure

### shop-application
- depends on shop-domain
- used by shop-api, shop-infrastructure

### shop-domain
- no project references
- used by shop-application

### shop-infrastructure
- depends on shop-application
- used by shop-api

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

