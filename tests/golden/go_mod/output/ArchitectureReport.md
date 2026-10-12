# Architecture Report

## Repository Information

**Repository Name:** go_mod

**Technology Stack:**

- Go

---

## Executive Summary

go_mod has 2 projects (2 production, 0 test) with 1 project references between them. The analysis found no structural concerns.

---

[//]: # (c4:start)

## Architecture (C4 model)

> Drawn from code facts only: no `c4-model.json` yet, so people, external purposes, descriptions and key flows are missing and the System Context level is left out. Write `c4-model.json` and run `render_c4.py` to complete it.

### Level 2: Containers

```mermaid
flowchart TB
    subgraph boundary["`**go_mod** [Software System]`"]
        api["`**api**
[Container: Go]
app`"]
    end
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class api container
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

| Container | Technology | Responsibility | Code |
|---|---|---|---|
| **api** (container) | Go | app | `cmd/api` |

### Level 3: Components

For each container: the modules it is built from (when it has several), then the code structure inside them (packages or namespaces and the imports between them).

#### api

```mermaid
flowchart TB
    subgraph boundary["`**api** [Container]`"]
        cmd_api["`**cmd/api**
[Component]`"]
        internal_store["`**internal/store**
[Component]`"]
    end
    cmd_api --> internal_store
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class cmd_api,internal_store component
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

### C4 files

- [c4-container.mmd](c4-container.mmd)
- [c4-component-api.mmd](c4-component-api.mmd)
- [c4-facts.json](c4-facts.json)

[//]: # (c4:end)

---

## Architectural Observations

### Strengths

- No circular project references.
- Projects with no project references (the core that the rest builds on): internal/store.

### Concerns

No automated concerns detected.

---

## Recommendations

No changes recommended from the automated checks. Review the diagram for boundaries the checks cannot see.

---

## Appendix: Project Dependency Graph

Every project or module and every reference between them, tests included. The automated checks above (cycles, stray projects, untested projects) are based on this graph.

**Solutions / build roots:** none found

**Project folders:** cmd, internal

<details>
<summary>Full dependency graph</summary>

```mermaid
graph TD
    subgraph group_cmd["cmd"]
        cmd_api["cmd/api"]
    end
    subgraph group_internal["internal"]
        internal_store["internal/store"]
    end
    cmd_api --> internal_store
```

</details>

### Components

| Project | Ecosystem | Folder | Kind | Depends on | Used by |
|---|---|---|---|---|---|
| cmd/api | Go | cmd | production | 1 | 0 |
| internal/store | Go | internal | production | 0 | 1 |

### Dependency Analysis

### cmd/api
- depends on internal/store

### internal/store
- no project references
- used by cmd/api

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

