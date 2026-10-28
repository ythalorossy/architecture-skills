# Architecture Report

## Repository Information

**Repository Name:** shared_libs

**Technology Stack:**

- .NET

---

## Executive Summary

[//]: # (summary:start)

shared_libs has 5 projects (5 production, 0 tests) with 4 project references between them.

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
| Light blue box | **Component** — a module, package or namespace inside one container. |
| Pale dashed box | Used by most of the other components, drawn in another part of the same view, or shared with another container and drawn once in a shared-libraries view. |
| Dashed grey outline | The system or the container the diagram is about. |
| Solid arrow | A dependency or a call, labelled with what it does and the technology it uses. |
| Dashed arrow | A dependency on a component drawn in another part of the same view. |

### Level 2: Containers

```mermaid
---
title: "shared_libs · Containers"
---
flowchart TB
    subgraph boundary["shared_libs [Software System]"]
        shop_admin["Shop.Admin<br/>[Container: ASP.NET Core, net8.0]<br/>web api"]
        shop_api["Shop.Api<br/>[Container: ASP.NET Core, net8.0]<br/>web api"]
        shop_worker["Shop.Worker<br/>[Container: .NET Worker Service, net8.0]<br/>worker"]
    end
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class shop_admin,shop_api,shop_worker container
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

| Container | Technology | Responsibility | Code |
|---|---|---|---|
| **Shop.Admin** (container) | ASP.NET Core, net8.0 | web api | `src/Shop.Admin` |
| **Shop.Api** (container) | ASP.NET Core, net8.0 | web api | `src/Shop.Api` |
| **Shop.Worker** (container) | .NET Worker Service, net8.0 | worker | `src/Shop.Worker` |

### Level 3: Components

For each container: the modules it is built from (when it has several), then the code structure inside them (packages or namespaces and the imports between them).

#### Shop.Admin

> Shop.Contracts is shared with another container and drawn once in c4-component-shared.mmd.

```mermaid
---
title: "Shop.Admin"
---
flowchart TB
    subgraph boundary["Shop.Admin [Container]"]
        Shop_Admin["Shop.Admin<br/>[Component]"]
    end
    shared_libraries["Shared libraries (1)<br/>[Component, drawn once in c4-component-shared.mmd]"]
    Shop_Admin -.-> shared_libraries
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class Shop_Admin component
    class shared_libraries shared
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

#### Shop.Admin · code structure

> The packages of Shop.Contracts are drawn once in c4-structure-shared.mmd: it is shared with another container.

```mermaid
---
title: "Shop.Admin · code structure"
---
flowchart TB
    subgraph boundary["Shop.Admin · code structure [Container]"]
        Shop_Admin___root["(root)<br/>[Component]"]
    end
    shared_libraries["Shared libraries (1)<br/>[Component, drawn once in c4-structure-shared.mmd]"]
    Shop_Admin___root -.-> shared_libraries
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class Shop_Admin___root component
    class shared_libraries shared
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

#### Shop.Api

> 2 components are shared with other containers and drawn once in c4-component-shared.mmd: Shop.Contracts, Shop.Core.

```mermaid
---
title: "Shop.Api"
---
flowchart TB
    subgraph boundary["Shop.Api [Container]"]
        Shop_Api["Shop.Api<br/>[Component]"]
    end
    shared_libraries["Shared libraries (2)<br/>[Component, drawn once in c4-component-shared.mmd]"]
    Shop_Api -.-> shared_libraries
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class Shop_Api component
    class shared_libraries shared
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

#### Shop.Api · code structure

> The packages of 2 shared libraries are drawn once in c4-structure-shared.mmd: Shop.Contracts, Shop.Core.

```mermaid
---
title: "Shop.Api · code structure"
---
flowchart TB
    subgraph boundary["Shop.Api · code structure [Container]"]
        Shop_Api___root["(root)<br/>[Component]"]
    end
    shared_libraries["Shared libraries (2)<br/>[Component, drawn once in c4-structure-shared.mmd]"]
    Shop_Api___root -.-> shared_libraries
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class Shop_Api___root component
    class shared_libraries shared
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

#### Shop.Worker

> 2 components are shared with other containers and drawn once in c4-component-shared.mmd: Shop.Contracts, Shop.Core.

```mermaid
---
title: "Shop.Worker"
---
flowchart TB
    subgraph boundary["Shop.Worker [Container]"]
        Shop_Worker["Shop.Worker<br/>[Component]"]
    end
    shared_libraries["Shared libraries (2)<br/>[Component, drawn once in c4-component-shared.mmd]"]
    Shop_Worker -.-> shared_libraries
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class Shop_Worker component
    class shared_libraries shared
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

#### Shop.Worker · code structure

> The packages of 2 shared libraries are drawn once in c4-structure-shared.mmd: Shop.Contracts, Shop.Core.

```mermaid
---
title: "Shop.Worker · code structure"
---
flowchart TB
    subgraph boundary["Shop.Worker · code structure [Container]"]
        Shop_Worker___root["(root)<br/>[Component]"]
    end
    shared_libraries["Shared libraries (2)<br/>[Component, drawn once in c4-structure-shared.mmd]"]
    Shop_Worker___root -.-> shared_libraries
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class Shop_Worker___root component
    class shared_libraries shared
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

#### shared_libs · Shared libraries

> Components used by more than one container, drawn once here instead of in each container's diagram: Shop.Contracts (shop-admin, shop-api, shop-worker); Shop.Core (shop-api, shop-worker).

```mermaid
---
title: "shared_libs · Shared libraries"
---
flowchart TB
    subgraph boundary["shared_libs · Shared libraries"]
        Shop_Contracts["Contracts<br/>[Component]"]
        Shop_Core["Core<br/>[Component]"]
    end
    shop_admin["Shop.Admin<br/>[Container: ASP.NET Core, net8.0]<br/>web api"]
    shop_admin -->|"Uses"| Shop_Contracts
    shop_api["Shop.Api<br/>[Container: ASP.NET Core, net8.0]<br/>web api"]
    shop_api -->|"Uses"| Shop_Core
    shop_worker["Shop.Worker<br/>[Container: .NET Worker Service, net8.0]<br/>worker"]
    shop_worker -->|"Uses"| Shop_Core
    Shop_Core --> Shop_Contracts
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class Shop_Contracts,Shop_Core component
    class shop_admin,shop_api,shop_worker container
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

#### shared_libs · Shared libraries, code structure

> The packages inside the libraries used by more than one container, drawn once here instead of inside every container that uses them.

```mermaid
---
title: "shared_libs · Shared libraries, code structure"
---
flowchart TB
    subgraph boundary["shared_libs · Shared libraries, code structure"]
        subgraph module_Shop_Contracts["Shop.Contracts"]
            Shop_Contracts___root["(root)<br/>[Component]"]
        end
        subgraph module_Shop_Core["Shop.Core"]
            Shop_Core___root["(root)<br/>[Component]"]
        end
    end
    Shop_Core___root --> Shop_Contracts___root
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class Shop_Contracts___root,Shop_Core___root component
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
    style module_Shop_Contracts fill:#f4f8fc,stroke:#9fb6cc
    style module_Shop_Core fill:#f4f8fc,stroke:#9fb6cc
```

### API endpoints

2 HTTP route(s) declared in code.

**Shop.Admin**

| Method | Path | Declared in |
|---|---|---|
| GET | `/admin/orders` | `src/Shop.Admin/Program.cs:5` |

**Shop.Api**

| Method | Path | Declared in |
|---|---|---|
| GET | `/orders/{id}` | `src/Shop.Api/Program.cs:6` |

### Technology inventory

Runtime, frameworks and key libraries declared in each container's build files.

| Container | Declared |
|---|---|
| **Shop.Admin** | `net8.0` |
| **Shop.Api** | `net8.0` |
| **Shop.Worker** | `net8.0` |

### C4 files

- [c4-container.mmd](c4-container.mmd)
- [c4-component-shop-admin.mmd](c4-component-shop-admin.mmd)
- [c4-structure-shop-admin.mmd](c4-structure-shop-admin.mmd)
- [c4-component-shop-api.mmd](c4-component-shop-api.mmd)
- [c4-structure-shop-api.mmd](c4-structure-shop-api.mmd)
- [c4-component-shop-worker.mmd](c4-component-shop-worker.mmd)
- [c4-structure-shop-worker.mmd](c4-structure-shop-worker.mmd)
- [c4-component-shared.mmd](c4-component-shared.mmd)
- [c4-structure-shared.mmd](c4-structure-shared.mmd)
- [c4-facts.json](c4-facts.json)

[//]: # (c4:end)

---

## Architectural Observations

### Strengths

[//]: # (strengths:start)

- No circular project references.
- Projects with no project references (the core that the rest builds on): Shop.Contracts.
- Every project is listed in a solution, workspace or aggregator build.

[//]: # (strengths:end)

### Concerns

No automated concerns detected.

---

## Recommendations

No changes recommended from the automated checks. Review the diagram for boundaries the checks cannot see.

---

## Appendix: Project Dependency Graph

Every project or module and every reference between them, tests included. The automated checks above (cycles, stray projects, untested projects) are based on this graph.

**Solutions / build roots:** Shop.sln

**Project folders:** src

<details>
<summary>Full dependency graph</summary>

```mermaid
---
title: "shared_libs · Project dependency graph"
---
graph TD
    subgraph group_src["src"]
        Shop_Admin["Shop.Admin"]
        Shop_Api["Shop.Api"]
        Shop_Contracts["Shop.Contracts"]
        Shop_Core["Shop.Core"]
        Shop_Worker["Shop.Worker"]
    end
    Shop_Admin --> Shop_Contracts
    Shop_Api --> Shop_Core
    Shop_Core --> Shop_Contracts
    Shop_Worker --> Shop_Core
```

</details>

### Components

| Project | Ecosystem | Folder | Kind | Depends on | Used by |
|---|---|---|---|---|---|
| Shop.Admin | .NET | src | production | 1 | 0 |
| Shop.Api | .NET | src | production | 1 | 0 |
| Shop.Contracts | .NET | src | production | 0 | 2 |
| Shop.Core | .NET | src | production | 1 | 2 |
| Shop.Worker | .NET | src | production | 1 | 0 |

### Dependency Analysis

### Shop.Admin
- depends on Shop.Contracts

### Shop.Api
- depends on Shop.Core

### Shop.Contracts
- no project references
- used by Shop.Admin, Shop.Core

### Shop.Core
- depends on Shop.Contracts
- used by Shop.Api, Shop.Worker

### Shop.Worker
- depends on Shop.Core

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

