# Architecture Report

## Repository Information

**Repository Name:** python_dist

**Technology Stack:**

- Python

---

## Executive Summary

[//]: # (summary:start)

python_dist has 2 projects (2 production, 0 test) with 1 project references between them.

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
| Dashed grey outline | The system or the container the diagram is about. |
| Solid arrow | A dependency or a call, labelled with what it does and the technology it uses. |

### Level 2: Containers

```mermaid
---
title: "python_dist · Containers"
---
flowchart TB
    subgraph boundary["python_dist [Software System]"]
        python_dist["python_dist<br/>[Container]"]
    end
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class python_dist container
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

| Container | Technology | Responsibility | Code |
|---|---|---|---|
| **python_dist** (container) | — | — | `.` |

### Level 3: Components

For each container: the modules it is built from (when it has several), then the code structure inside them (packages or namespaces and the imports between them).

#### python_dist

```mermaid
---
title: "python_dist"
---
flowchart TB
    subgraph boundary["python_dist [Container]"]
        acme_core["acme-core<br/>[Component]"]
        acme_web["acme-web<br/>[Component]"]
    end
    acme_web --> acme_core
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
    classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
    classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
    class acme_core,acme_web component
    style boundary fill:none,stroke:#444444,stroke-dasharray:6 4
```

### Technology inventory

Runtime, frameworks and key libraries declared in each container's build files.

| Container | Declared |
|---|---|
| **python_dist** | `acme-core>=1.0.0` |

### C4 files

- [c4-container.mmd](c4-container.mmd)
- [c4-component-python-dist.mmd](c4-component-python-dist.mmd)
- [c4-facts.json](c4-facts.json)

[//]: # (c4:end)

---

## Architectural Observations

### Strengths

[//]: # (strengths:start)

- No circular project references.
- Projects with no project references (the core that the rest builds on): acme-core.

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

**Project folders:** packages

<details>
<summary>Full dependency graph</summary>

```mermaid
---
title: "python_dist · Project dependency graph"
---
graph TD
    subgraph group_packages["packages"]
        acme_core["acme-core"]
        acme_web["acme-web"]
    end
    acme_web --> acme_core
```

</details>

### Components

| Project | Ecosystem | Folder | Kind | Depends on | Used by |
|---|---|---|---|---|---|
| acme-core | Python | packages | production | 0 | 1 |
| acme-web | Python | packages | production | 1 | 0 |

### Dependency Analysis

### acme-core
- no project references
- used by acme-web

### acme-web
- depends on acme-core

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

