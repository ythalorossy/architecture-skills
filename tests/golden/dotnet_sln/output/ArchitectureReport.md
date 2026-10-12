# Architecture Report

## Repository Information

**Repository Name:** dotnet_sln

**Technology Stack:**

- .NET

---

## Executive Summary

dotnet_sln has 2 projects (2 production, 0 test) with 1 project references between them. The analysis found no structural concerns.

---

[//]: # (c4:start)

## Architecture (C4 model)

> Drawn from code facts only: no `c4-model.json` yet, so people, external purposes, descriptions and key flows are missing and the System Context level is left out. Write `c4-model.json` and run `render_c4.py` to complete it.

### Key

What the shapes and lines in the diagrams below mean.

| Symbol | Meaning |
|---|---|
| Blue box | **Container** — an application or service that runs on its own. |
| Light blue box | **Component** — a module, package or namespace inside one container. |
| Dashed grey outline | The system or the container the diagram is about. |
| Solid arrow | A dependency or a call, labelled with what it does and the technology it uses. |

### Level 2: Containers

```mermaid
---
title: "dotnet_sln · Containers"
---
flowchart TB
    subgraph boundary["dotnet_sln [Software System]"]
        dotnet_sln["dotnet_sln<br/>[Container]"]
    end
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class dotnet_sln container
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

| Container | Technology | Responsibility | Code |
|---|---|---|---|
| **dotnet_sln** (container) | — | — | `.` |

### Level 3: Components

For each container: the modules it is built from (when it has several), then the code structure inside them (packages or namespaces and the imports between them).

#### dotnet_sln

```mermaid
---
title: "dotnet_sln"
---
flowchart TB
    subgraph boundary["dotnet_sln [Container]"]
        Core["Core<br/>[Component]"]
        Web["Web<br/>[Component]"]
    end
    Web --> Core
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class Core,Web component
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

### Technology inventory

Runtime, frameworks and key libraries declared in each container's build files.

| Container | Declared |
|---|---|
| **dotnet_sln** | `net8.0` |

### C4 files

- [c4-container.mmd](c4-container.mmd)
- [c4-component-dotnet-sln.mmd](c4-component-dotnet-sln.mmd)
- [c4-facts.json](c4-facts.json)

[//]: # (c4:end)

---

## Architectural Observations

### Strengths

- No circular project references.
- Projects with no project references (the core that the rest builds on): Core.
- Every project is listed in a solution, workspace or aggregator build.

### Concerns

No automated concerns detected.

---

## Recommendations

No changes recommended from the automated checks. Review the diagram for boundaries the checks cannot see.

---

## Appendix: Project Dependency Graph

Every project or module and every reference between them, tests included. The automated checks above (cycles, stray projects, untested projects) are based on this graph.

**Solutions / build roots:** MyApp.sln

**Project folders:** none

<details>
<summary>Full dependency graph</summary>

```mermaid
graph TD
    Core["Core"]
    Web["Web"]
    Web --> Core
```

</details>

### Components

| Project | Ecosystem | Folder | Kind | Depends on | Used by |
|---|---|---|---|---|---|
| Core | .NET | - | production | 0 | 1 |
| Web | .NET | - | production | 1 | 0 |

### Dependency Analysis

### Core
- no project references
- used by Web

### Web
- depends on Core

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

