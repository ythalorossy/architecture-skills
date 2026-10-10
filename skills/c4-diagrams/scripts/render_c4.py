"""
Draw the C4 diagrams (context, container, component, code structure, key
flows, deployment) and the facts tables (endpoints, configuration, technology
inventory) from c4-facts.json and, when present, the c4-model.json the agent
writes on top of it.

    python3 render_c4.py <output folder> [--facts-only]

Writes c4-*.mmd / c4-*.svg into the output folder and replaces the C4 block of
ArchitectureReport.md. Exits with status 1 when c4-model.json does not match the
facts (missing elements, unknown ids), listing every problem.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import json
import re
import sys
import textwrap

SKILL_DIR = Path(__file__).resolve().parent.parent
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from scripts.cli_support import UserError, require_python, run_cli

# Must run before the imports below: they reach python_projects, which needs
# tomllib (3.11+) and would otherwise fail with an opaque ImportError.
require_python()

from scripts.generate_mermaid import _node_ids, render_svg
from scripts import code_diagrams


MAX_COMPONENTS = 20
ROW_WIDTH = 6
# Markdown "comments" (empty link definitions) rather than HTML comments: every
# renderer drops them, and none can swallow the content between them.
BLOCK_START = "[//]: # (c4:start)"
BLOCK_END = "[//]: # (c4:end)"
OLD_MARKERS = ("<!-- c4:start -->", "<!-- c4:end -->")

STYLES = [
    "classDef person fill:#08427b,stroke:#052e56,color:#ffffff",
    "classDef container fill:#1168bd,stroke:#0b4884,color:#ffffff",
    "classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff",
    "classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000",
    "classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff",
    "classDef shared fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3",
]


# ---------- model ----------

def facts_only_model(facts):
    """A model with no judgement in it: containers, stores and external systems as found."""
    containers = [
        {
            "id": c["id"], "name": c["name"], "technology": c["technology"],
            "description": c["kind"].replace("-", " ") if c["kind"] != "unknown" else "",
            "type": "container", "evidence": c["evidence"],
        }
        for c in facts["containers"]
    ] + [
        {
            "id": s["id"], "name": s["name"], "technology": s["technology"], "description": "",
            "type": "database", "evidence": s["evidence"],
        }
        for s in facts["data_stores"]
    ]
    externals = [
        {
            "id": e["id"], "name": e["name"],
            "description": e["technology"] if e["technology"] != e["name"] else "",
            "evidence": e["evidence"],
        }
        for e in facts["external_systems"]
    ]
    relationships = [
        {"from": r["from"], "to": r["to"], "description": r["description"], "technology": r.get("technology", "")}
        for r in facts.get("relationships", [])
    ] + [
        {"from": user, "to": item["id"], "description": "Reads/writes" if kind == "store" else "Calls"}
        for kind, items in (("store", facts["data_stores"]), ("external", facts["external_systems"]))
        for item in items
        for user in item["used_by"]
    ]
    return {
        "system": {"name": facts["repository"], "description": ""},
        "people": [],
        "containers": containers,
        "external_systems": externals,
        "relationships": relationships,
        "components": {},
        "flows": [],
        "excluded": [],
        "_facts_only": True,
    }


def _covers(element):
    return element.get("facts") or [element["id"]]


def validate(model, facts):
    """Return (errors, warnings). Errors make the model unusable."""
    errors, warnings = [], []

    elements = {}
    for section in ("people", "containers", "external_systems"):
        for element in model.get(section) or []:
            if "id" not in element or "name" not in element:
                errors.append(f"{section}: every element needs an id and a name ({element})")
                continue
            if element["id"] in elements:
                errors.append(f"duplicate id: {element['id']}")
            elements[element["id"]] = section
            if not element.get("evidence") and not element.get("assumption"):
                warnings.append(f"{element['id']}: no evidence and not marked as an assumption")

    if model.get("system", {}).get("name") is None:
        errors.append("system.name is missing")

    covered = {fact for section in ("containers", "external_systems") for e in model.get(section) or [] for fact in _covers(e)}
    covered |= {item["id"] for item in model.get("excluded") or []}
    for kind in ("containers", "data_stores", "external_systems"):
        for fact in facts[kind]:
            if fact["id"] not in covered:
                errors.append(
                    f"{fact['id']} ({fact['name']}) was found in the code but is not in the model; "
                    "add it (or list it in `facts` of an element) or put it in `excluded` with a reason"
                )

    for relationship in model.get("relationships") or []:
        for end in ("from", "to"):
            if relationship.get(end) not in elements:
                errors.append(f"relationship {relationship.get('from')} -> {relationship.get('to')}: unknown id {relationship.get(end)!r}")

    component_ids = all_component_ids(model, facts)
    for container_id, descriptions in (model.get("components") or {}).items():
        if elements.get(container_id) != "containers":
            errors.append(f"components: {container_id!r} is not a container id")
            continue
        for component in descriptions:
            if component not in component_ids.get(container_id, set()):
                warnings.append(f"components.{container_id}: {component!r} is not a component of that container; its description is ignored")

    known = set(elements) | {c for ids in component_ids.values() for c in ids}
    for flow in model.get("flows") or []:
        if not flow.get("name") or not flow.get("steps"):
            errors.append(f"flows: every flow needs a name and steps ({flow.get('id') or flow.get('name')})")
            continue
        for number, step in enumerate(flow["steps"], 1):
            for end in ("from", "to"):
                if step.get(end) not in known:
                    errors.append(
                        f"flow {flow['name']!r} step {number}: unknown {end} {step.get(end)!r} "
                        "(use a person, container or external system id, or a component id from c4-facts.json)"
                    )

    # Links the code or config declares should appear in the model.
    mapped = {}
    for section in ("containers", "external_systems"):
        for element in model.get(section) or []:
            for fact in _covers(element):
                mapped[fact] = element["id"]
    drawn = {(r.get("from"), r.get("to")) for r in model.get("relationships") or []}
    for r in facts.get("relationships", []):
        a, b = mapped.get(r["from"]), mapped.get(r["to"])
        if a and b and a != b and (a, b) not in drawn:
            warnings.append(f"{a} -> {b} is declared in {', '.join(r['evidence'])} ({r['source']}) but has no relationship in the model")

    return errors, warnings


def all_component_ids(model, facts):
    """{model container id: {module and code component ids}}."""
    result = {}
    for element in model.get("containers") or []:
        ids = set()
        for fact in _covers(element):
            container = next((c for c in facts["containers"] if c["id"] == fact), None)
            if container:
                ids |= set((container.get("components") or {}).get("nodes", {}))
                ids |= set((container.get("code_components") or {}).get("nodes", {}))
        result[element["id"]] = ids
    return result


def _unreviewed_facts_warnings(model, facts):
    """
    Return model-tier warning messages for every fact not covered by the model.
    Used when rendering on drift to surface new facts for the agent to review.
    """
    covered = {fact for section in ("containers", "external_systems") for e in model.get(section) or [] for fact in _covers(e)}
    covered |= {item["id"] for item in model.get("excluded") or []}
    warnings = []
    for kind in ("containers", "data_stores", "external_systems"):
        for fact in facts[kind]:
            if fact["id"] not in covered:
                warnings.append(
                    f"{fact['id']} ({fact['name']}) was found in the code but is not in the model; "
                    "add it (or list it in `facts` of an element) or put it in `excluded` with a reason"
                )
    return warnings


# ---------- mermaid ----------

def _clean(text):
    return str(text).replace("`", "'").replace('"', "'").replace("<", "‹").replace(">", "›")


def _wrap(text, width=34):
    return "\n".join(textwrap.wrap(_clean(text), width)) if text else ""


def _label(name, kind, description=""):
    lines = [f"**{_clean(name)}**", f"[{_clean(kind)}]"]
    if description:
        lines.append(_wrap(description))
    return '"`' + "\n".join(lines) + '`"'


def _edge_label(description, technology=""):
    text = _wrap(description, 28) if description else ""
    if technology:
        text += ("\n" if text else "") + f"[{_clean(technology)}]"
    return f'|"`{text}`"|' if text else ""


class Diagram:
    def __init__(self):
        self.lines = []
        self.classes = {}
        self.ids = {}

    def id(self, key):
        if key not in self.ids:
            self.ids[key] = _node_ids(list(self.ids) + [key])[key]
        return self.ids[key]

    def node(self, key, label, cls, shape="rect", indent="    "):
        open_, close = {"rect": ("[", "]"), "db": ("[(", ")]"), "round": ("(", ")")}[shape]
        self.lines.append(f"{indent}{self.id(key)}{open_}{label}{close}")
        self.classes.setdefault(cls, []).append(self.id(key))

    def edge(self, source, target, label="", dashed=False):
        arrow = "-.->" if dashed else "-->"
        self.lines.append(f"    {self.id(source)} {arrow}{label} {self.id(target)}")

    def text(self, boundaries=()):
        out = ["---", "config:", "  layout: elk", "---", "flowchart TB"] + self.lines + ["    " + s for s in STYLES]
        for cls, ids in self.classes.items():
            out.append(f"    class {','.join(ids)} {cls}")
        for boundary in boundaries:
            out.append(f"    style {boundary} fill:none,stroke:#444444,stroke-dasharray:6 4")
        return "\n".join(out) + "\n"


def _element_node(diagram, element, section, indent="    "):
    if section == "people":
        diagram.node(element["id"], _label(element["name"], "Person", element.get("description")), "person", "round", indent)
    elif section == "external_systems":
        diagram.node(element["id"], _label(element["name"], "Software System", element.get("description")), "external", "rect", indent)
    else:
        kind = "Container" + (f": {element['technology']}" if element.get("technology") else "")
        shape = "db" if element.get("type") in ("database", "queue") else "rect"
        diagram.node(element["id"], _label(element["name"], kind, element.get("description")), "container", shape, indent)


def _merge_relationships(relationships):
    """One edge per (from, to): keep the first description, collect technologies."""
    merged = {}
    for r in relationships:
        key = (r["from"], r["to"])
        if key[0] == key[1]:
            continue
        if key not in merged:
            merged[key] = dict(r)
    return list(merged.values())


def context_diagram(model):
    d = Diagram()
    system = model["system"]
    inside = {c["id"] for c in model["containers"] if not c.get("external")}
    outside = {c["id"]: c for c in model["containers"] if c.get("external")}

    for person in model["people"]:
        _element_node(d, person, "people")
    d.node("__system__", _label(system["name"], "Software System", system.get("description")), "system")
    for external in model["external_systems"]:
        _element_node(d, external, "external_systems")
    for container in outside.values():
        d.node(container["id"], _label(container["name"], "Software System", container.get("description")), "external")

    lift = lambda node: "__system__" if node in inside else node
    edges = _merge_relationships([
        {**r, "from": lift(r["from"]), "to": lift(r["to"])} for r in model["relationships"]
    ])
    for r in edges:
        d.edge(r["from"], r["to"], _edge_label(r.get("description"), r.get("technology")))
    return d.text()


def container_diagram(model):
    d = Diagram()
    for person in model["people"]:
        _element_node(d, person, "people")

    boundary = d.id("__boundary__")
    d.lines.append(f'    subgraph {boundary}["`**{_clean(model["system"]["name"])}** [Software System]`"]')
    for container in model["containers"]:
        if not container.get("external"):
            _element_node(d, container, "containers", indent="        ")
    d.lines.append("    end")

    for container in model["containers"]:
        if container.get("external"):
            d.node(container["id"], _label(container["name"], "Software System", container.get("description")), "external")
    for external in model["external_systems"]:
        _element_node(d, external, "external_systems")

    for r in _merge_relationships(model["relationships"]):
        d.edge(r["from"], r["to"], _edge_label(r.get("description"), r.get("technology")))
    return d.text([boundary])


def _short_names(nodes):
    """Drop the dotted/slashed prefix every node shares (rag_docling.x -> x)."""
    split = {n: re.split(r"(?<=[./])", n) for n in nodes}
    dotted = [parts for parts in split.values() if len(parts) > 1]
    if len(dotted) < 2:
        return {n: n for n in nodes}
    prefix = []
    for column in zip(*dotted):
        if len(set(column)) != 1:
            break
        prefix.append(column[0])
    prefix = "".join(prefix)
    return {n: (n[len(prefix):] if prefix and n.startswith(prefix) and len(n) > len(prefix) else n) for n in nodes}


def _transitive_reduction(edges):
    """Drop an edge only while another path still connects its ends (safe with cycles)."""
    current = {a: list(targets) for a, targets in edges.items()}

    def reachable(start, goal, skip):
        seen, stack = set(), [t for t in current.get(start, []) if (start, t) != skip]
        while stack:
            node = stack.pop()
            if node == goal:
                return True
            if node in seen:
                continue
            seen.add(node)
            stack += current.get(node, [])
        return False

    for a in sorted(current):
        for b in list(current[a]):
            if reachable(a, b, (a, b)):
                current[a].remove(b)
    return current


def _component_views(graph, overview=True, full_list="the dependency graph appendix"):
    """
    Split one container's components into readable views: [(suffix, title, nodes, edges, notes)].
    Shortcut edges are hidden when the graph is dense; above MAX_COMPONENTS nodes the
    view is grouped by folder/module (an overview plus one view per group), and
    components most others use are moved to a "shared" box.
    """
    nodes = graph["nodes"]
    edges = graph["edges"]
    notes = []

    edge_count = sum(len(t) for t in edges.values())
    if edge_count > 1.5 * len(nodes):
        reduced = _transitive_reduction(edges)
        hidden = edge_count - sum(len(t) for t in reduced.values())
        if hidden:
            notes.append(
                f"{hidden} of {edge_count} dependencies are hidden because a longer path already shows them "
                f"(A → C is left out when A → B → C is drawn). The full list is in {full_list}."
            )
            edges = reduced

    groups = {}
    for node, info in nodes.items():
        groups.setdefault(info["group"] or "(root)", []).append(node)

    if len(nodes) > MAX_COMPONENTS and len(groups) > 1:
        group_of = {n: (nodes[n]["group"] or "(root)") for n in nodes}
        group_edges = {}
        for source, targets in edges.items():
            for target in targets:
                a, b = group_of[source], group_of[target]
                if a != b:
                    group_edges.setdefault(a, set()).add(b)
        overview_nodes = {g: {"group": "", "label": f"{g} ({len(ns)})"} for g, ns in groups.items()}
        views = [("", "folders", overview_nodes, {g: sorted(t) for g, t in group_edges.items()},
                  notes + [f"{len(nodes)} components grouped by folder; each part is drawn below."])] if overview else []
        # Pack whole groups (folders/modules) into diagrams of up to MAX_COMPONENTS
        # nodes, biggest first, so small modules share a diagram.
        packs = []
        for group, members in sorted(groups.items(), key=lambda g: (-len(g[1]), g[0])):
            if len(members) < 2 and overview:
                continue
            target = next((pack for pack in packs if sum(len(m) for _, m in pack) + len(members) <= MAX_COMPONENTS), None)
            if target is None:
                packs.append([(group, members)])
            else:
                target.append((group, members))
        for index, pack in enumerate(packs, 1):
            members = [n for _, m in pack for n in m]
            member_set = set(members)
            first_notes = [] if overview or index > 1 else notes + [f"{len(nodes)} components, drawn in {len(packs)} parts."]
            views.append((
                f"-part{index}",
                ", ".join(sorted(g for g, _ in pack)) if len(pack) <= 3 else f"part {index} of {len(packs)}",
                {n: nodes[n] for n in members},
                {n: [t for t in edges.get(n, []) if t in member_set] for n in members},
                first_notes,
            ))
        return views

    shared = []
    if len(nodes) > MAX_COMPONENTS:
        indegree = {n: 0 for n in nodes}
        for targets in edges.values():
            for target in targets:
                indegree[target] += 1
        threshold = max(3, len(nodes) // 2)
        shared = [n for n, count in indegree.items() if count >= threshold]
        if shared:
            notes.append(
                "Used by most other components, drawn in the Shared box without their incoming edges: "
                + ", ".join(f"{n} ({indegree[n]})" for n in shared) + "."
            )
            edges = {n: [t for t in targets if t not in shared] for n, targets in edges.items()}
    if len(nodes) > MAX_COMPONENTS:
        notes.append(f"{len(nodes)} components: above the {MAX_COMPONENTS} that stay readable in one diagram.")

    return [("", "", {n: {**nodes[n], "shared": n in shared} for n in nodes}, edges, notes)]


def _container_lookup(model):
    by_fact = {}
    for section in ("containers", "external_systems"):
        for element in model[section]:
            for fact in _covers(element):
                by_fact[fact] = element
    return by_fact


def _graph_diagram(model, facts, container, container_fact, title, nodes, edges, texts, usage_key):
    """One component-style diagram: nodes inside the container boundary (grouped by module when
    there are several), edges between them, and the stores/external systems they use."""
    by_fact = _container_lookup(model)
    relationship_text = {(r["from"], r["to"]): r for r in model["relationships"]}
    d = Diagram()
    short = _short_names(list(nodes))
    boundary = d.id("__boundary__")
    d.lines.append(f'    subgraph {boundary}["`**{_clean(title)}** [Container]`"]')
    regular = [n for n, info in nodes.items() if not info.get("shared")]
    shared = [n for n, info in nodes.items() if info.get("shared")]

    def label_of(node):
        return (nodes[node].get("label") or short[node]).replace(" (files)", " (root files)")

    modules = {}
    for node in regular:
        modules.setdefault(nodes[node].get("module"), []).append(node)
    boxes = []
    if usage_key == "used_by_code" and len(modules) > 1:
        for module, members in sorted(modules.items(), key=lambda m: str(m[0])):
            box = d.id(f"__module__{module}")
            boxes.append(box)
            d.lines.append(f'        subgraph {box}["`{_clean(module)}`"]')
            for node in members:
                d.node(node, _label(label_of(node), "Component", texts.get(node, "")), "component", indent="            ")
            d.lines.append("        end")
    else:
        for node in regular:
            d.node(node, _label(label_of(node), "Component", texts.get(node, "")), "component", indent="        ")
    if shared:
        d.lines.append(f'        subgraph {d.id("__shared__")}["Shared"]')
        for node in shared:
            d.node(node, _label(label_of(node), "Component", texts.get(node, "")), "shared", indent="            ")
        d.lines.append("        end")
    d.lines.append("    end")

    for source, targets in edges.items():
        for target in targets:
            if source in nodes and target in nodes:
                d.edge(source, target)

    # ELK puts every top-level component in one row; invisible links
    # stack them in rows of ROW_WIDTH so wide diagrams stay readable.
    if not boxes:
        targeted = {t for targets in edges.values() for t in targets}
        roots = [n for n in regular if n not in targeted]
        for upper, lower in zip(roots, roots[ROW_WIDTH:]):
            d.lines.append(f"    {d.id(upper)} ~~~ {d.id(lower)}")

    for kind in ("data_stores", "external_systems"):
        for fact in facts[kind]:
            element = by_fact.get(fact["id"])
            users = [n for n in (fact.get(usage_key) or {}).get(container_fact["id"], []) if n in nodes]
            if element is None or not users:
                continue
            if element["id"] not in d.ids:
                section = "containers" if element in model["containers"] else "external_systems"
                _element_node(d, element, section)
            r = relationship_text.get((container["id"], element["id"]), {})
            for user in users:
                d.edge(user, element["id"], _edge_label(r.get("description", "Uses"), r.get("technology")))

    out = d.text([boundary])
    for box in boxes:
        out += f"    style {box} fill:#f4f8fc,stroke:#9fb6cc\n"
    return out


def component_diagrams(model, facts):
    """
    [(file stem, title, mermaid, notes, kind)] per container: its modules (when it has
    at least two) and the code structure inside them (packages/namespaces).
    """
    by_fact = _container_lookup(model)
    descriptions = model.get("components") or {}
    results = []

    for container_fact in facts["containers"]:
        container = by_fact.get(container_fact["id"])
        if container is None:
            continue  # excluded in the model
        texts = descriptions.get(container["id"]) or {}

        components = container_fact.get("components") or {}
        if len(components.get("nodes", {})) >= 2:
            for suffix, subtitle, nodes, edges, notes in _component_views(components):
                title = container["name"] + (f" / {subtitle}" if subtitle else "")
                stem = f"c4-component-{container['id']}{suffix}"
                mermaid = _graph_diagram(model, facts, container, container_fact, title, nodes, edges, texts, "used_by_components")
                results.append((stem, title, mermaid, notes, "modules"))

        code = container_fact.get("code_components") or {}
        if len(code.get("nodes", {})) >= 2:
            has_modules = len(components.get("nodes", {})) >= 2
            for suffix, subtitle, nodes, edges, notes in _component_views(
                code, overview=not has_modules, full_list="c4-facts.json (`code_components`)"
            ):
                title = f"{container['name']} · code structure" + (f" / {subtitle}" if subtitle else "")
                stem = f"c4-structure-{container['id']}{suffix}"
                mermaid = _graph_diagram(model, facts, container, container_fact, title, nodes, edges, texts, "used_by_code")
                results.append((stem, title, mermaid, notes, "code"))

    return results


def _participants(model, facts):
    """id -> (label, kind) for everything a flow step may reference."""
    found = {}
    for person in model.get("people") or []:
        found[person["id"]] = (person["name"], "actor")
    for section in ("containers", "external_systems"):
        for element in model.get(section) or []:
            found[element["id"]] = (element["name"], "participant")
    for container_fact in facts["containers"]:
        for key in ("components", "code_components"):
            for node, info in ((container_fact.get(key) or {}).get("nodes") or {}).items():
                label = info.get("label") or node
                if key == "code_components":
                    label = f"{info.get('module')}/{label}" if info.get("module") else label
                found.setdefault(node, (label, "participant"))
    return found


def _seq_text(text):
    """Message text for a sequence diagram: ';' and '#' end or start statements/entities in Mermaid."""
    return _clean(text).replace("#", "#35;").replace(";", "#59;").replace("\n", " ")


def flow_diagrams(model, facts):
    """[(stem, title, mermaid, description)] for each key flow in the model, as sequence diagrams."""
    participants = _participants(model, facts)
    results = []
    for index, flow in enumerate(model.get("flows") or [], 1):
        ids = {}
        used = []
        for step in flow["steps"]:
            for end in (step["from"], step["to"]):
                if end not in used:
                    used.append(end)
        safe = _node_ids(used)
        lines = ["sequenceDiagram"]
        for node in used:
            label, kind = participants.get(node, (node, "participant"))
            lines.append(f"    {kind} {safe[node]} as {_clean(label)}")
        for step in flow["steps"]:
            arrow = "-->>" if step.get("reply") else ("-)" if step.get("async") else "->>")
            text = _seq_text(step.get("description", ""))
            if step.get("technology"):
                text += f" [{_seq_text(step['technology'])}]"
            lines.append(f"    {safe[step['from']]}{arrow}{safe[step['to']]}: {text or ' '}")
            if step.get("note"):
                lines.append(f"    Note over {safe[step['to']]}: {_seq_text(step['note'])}")
        slug = re.sub(r"[^a-z0-9]+", "-", (flow.get("id") or flow["name"]).lower()).strip("-") or str(index)
        results.append((f"c4-flow-{slug}", flow["name"], "\n".join(lines) + "\n", flow.get("description", "")))
    return results


def deployment_diagram(facts, model):
    """Compose services as a deployment view: services, images/builds, published ports, depends_on."""
    services = (facts.get("deployment") or {}).get("compose") or []
    if not services:
        return None
    by_fact = _container_lookup(model)
    d = Diagram()
    host = d.id("__host__")
    d.lines.append(f'    subgraph {host}["`**Docker host** [docker compose]`"]')
    containers_by_service = {}
    for c in facts["containers"]:
        for service in c.get("compose_services") or []:
            containers_by_service[service] = c
    for service in services:
        image = service.get("image") or ""
        build = service.get("build")
        detail = (f"build {build}" if build else "") + (" · " if build and image else "") + image
        ports = ", ".join(service.get("ports") or [])
        name = service["name"]
        fact = containers_by_service.get(name)
        element = by_fact.get(fact["id"]) if fact else None
        if element and element["name"] != service["name"]:
            name = f"{service['name']} ({element['name']})"
        store = any(key in image.split(":")[0].lower() for key in ("postgres", "mysql", "mariadb", "mongo", "redis", "elastic", "opensearch", "rabbit", "kafka", "mssql", "minio", "memcached", "qdrant", "chroma"))
        lines = [f"**{_clean(name)}**", "[Container instance]"] + [_wrap(detail)] + ([f"ports {_clean(ports)}"] if ports else [])
        label = '"`' + "\n".join(l for l in lines if l) + '`"'
        d.node(f"svc:{service['name']}", label, "container", "db" if store else "rect", indent="        ")
    d.lines.append("    end")
    for service in services:
        for dependency in service.get("depends_on") or []:
            if any(s["name"] == dependency for s in services):
                d.edge(f"svc:{service['name']}", f"svc:{dependency}", _edge_label("depends on"))
    return d.text([host])


# ---------- output ----------

def _section(title, stem, mermaid, svg_ok, notes=(), intro=""):
    lines = [title, ""]
    if intro:
        lines += [_clean(intro), ""]
    lines += [f"> {note}" for note in notes] + ([""] if notes else [])
    if svg_ok:
        lines += [f"![{stem}]({stem}.svg)", "", "<details>", "<summary>Mermaid source</summary>", "",
                  "```mermaid", mermaid.rstrip(), "```", "", "</details>"]
    else:
        lines += ["```mermaid", mermaid.rstrip(), "```"]
    return "\n".join(lines) + "\n"


def _cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def _assumptions(model):
    items = []
    for section in ("people", "containers", "external_systems"):
        for element in model.get(section) or []:
            if element.get("assumption"):
                items.append(f"- **{element['name']}**: {element.get('description') or 'no description'}")
    for r in model.get("relationships") or []:
        if r.get("assumption"):
            items.append(f"- **{r['from']} → {r['to']}**: {r.get('description', '')}")
    return items


def _containers_table(model, facts):
    paths = {c["id"]: c.get("path") for c in facts["containers"]}
    rows = ["| Container | Technology | Responsibility | Code |", "|---|---|---|---|"]
    for element in model["containers"]:
        code = ", ".join(sorted({f"`{paths[f]}`" for f in _covers(element) if paths.get(f)})) or "—"
        kind = "data store" if element.get("type") in ("database", "queue") else "container"
        rows.append(f"| **{_cell(element['name'])}** ({kind}) | {_cell(element.get('technology') or '—')} | {_cell(element.get('description') or '—')} | {code} |")
    return rows


def _endpoints_section(facts, model):
    endpoints = facts.get("endpoints") or []
    if not endpoints:
        return []
    by_fact = _container_lookup(model)
    lines = ["### API endpoints", "", f"{len(endpoints)} HTTP route(s) declared in code.", ""]
    groups = {}
    for e in endpoints:
        element = by_fact.get(e["container"]) if e["container"] else None
        groups.setdefault(element["name"] if element else "Not in a container", []).append(e)
    for name, items in groups.items():
        lines += [f"**{_cell(name)}**", "", "| Method | Path | Declared in |", "|---|---|---|"]
        lines += [f"| {e['method']} | `{_cell(e['path'])}` | `{e['file']}:{e['line']}` |" for e in items]
        lines.append("")
    return lines


def _deployment_section(facts, model, svg_ok, mermaid):
    deployment = facts.get("deployment") or {}
    if not any(deployment.get(k) for k in ("compose", "dockerfiles", "kubernetes", "ci", "platforms")):
        return []
    lines = ["### Deployment", ""]
    if mermaid:
        lines.append(_section("#### docker compose", "c4-deployment", mermaid, svg_ok))
    if deployment.get("dockerfiles"):
        lines += ["#### Container images", "", "| Dockerfile | Build stages | Runtime image | Exposes | Starts with |", "|---|---|---|---|---|"]
        for f in deployment["dockerfiles"]:
            lines.append(
                f"| `{f['file']}` | {len(f['base_images'])} | `{_cell(f['runtime_image'] or '—')}` | {_cell(f['expose'] or '—')} | "
                f"{('`' + _cell(f['entrypoint']) + '`') if f['entrypoint'] else '—'} |"
            )
        lines.append("")
    if deployment.get("kubernetes"):
        lines += ["#### Kubernetes", "", "| Kind | Name | Images | File |", "|---|---|---|---|"]
        lines += [f"| {k['kind']} | {_cell(k['name'])} | {_cell(', '.join(k['images']) or '—')} | `{k['file']}` |" for k in deployment["kubernetes"]]
        lines.append("")
    tools = deployment.get("ci", []) + deployment.get("platforms", [])
    if tools:
        lines += ["#### CI and hosting files", ""]
        grouped = {}
        for t in tools:
            grouped.setdefault(t["tool"], []).append(t["file"])
        lines += [f"- **{tool}**: " + ", ".join(f"`{f}`" for f in files[:6]) + (" …" if len(files) > 6 else "") for tool, files in grouped.items()]
        lines.append("")
    elif deployment.get("compose") or deployment.get("dockerfiles"):
        lines += ["No CI pipeline or hosting configuration was found in the repository.", ""]
    return lines


def _configuration_section(facts, model):
    config = facts.get("configuration") or {}
    variables = config.get("variables") or []
    if not variables and not config.get("files"):
        return []
    by_fact = _container_lookup(model)
    lines = ["### Configuration", ""]
    if config.get("files"):
        lines += ["Config files: " + ", ".join(f"`{f}`" for f in config["files"]), ""]
    if variables:
        lines += ["| Variable | Default | Used by | Declared in |", "|---|---|---|---|"]
        for v in variables:
            users = ", ".join(sorted({by_fact[c]["name"] for c in v["containers"] if c in by_fact})) or "—"
            default = f"`{_cell(v['default'])}`" if v.get("default") not in (None, "") else "—"
            lines.append(f"| `{v['name']}` | {default} | {_cell(users)} | " + ", ".join(f"`{s}`" for s in v["sources"]) + " |")
        lines.append("")
    return lines


def _inventory_section(facts, model):
    by_fact = _container_lookup(model)
    rows = []
    for c in facts["containers"]:
        element = by_fact.get(c["id"])
        if element is None or not c.get("inventory"):
            continue
        rows.append(f"| **{_cell(element['name'])}** | " + ", ".join(f"`{_cell(i)}`" for i in c["inventory"]) + " |")
    if not rows:
        return []
    return ["### Technology inventory", "", "Runtime, frameworks and key libraries declared in each container's build files.", "",
            "| Container | Declared |", "|---|---|"] + rows + [""]


def render(output_dir, facts_only=False, svg=True, repo_override=None, collector=None, show_drift=False):
    output = Path(output_dir).resolve()
    facts_file = output / "c4-facts.json"
    if not facts_file.is_file():
        raise UserError(
            f"{facts_file} not found; run analyze_repository.py first"
        )
    facts = json.loads(facts_file.read_text(encoding="utf-8"))
    model_file = output / "c4-model.json"

    errors, warnings = [], []
    code_entries = []
    if facts_only or not model_file.is_file():
        model = facts_only_model(facts)
    else:
        model = json.loads(model_file.read_text(encoding="utf-8"))
        for key in ("people", "containers", "external_systems", "relationships", "excluded", "flows"):
            model.setdefault(key, [])
        errors, warnings = validate(model, facts)
        if errors:
            for err in errors:
                if collector:
                    collector.model_warning("render_c4", err)
            return {"errors": errors, "warnings": warnings}
        errors, code_warnings, code_entries = code_diagrams.prepare(
            model, facts, output, collector, repo_override=repo_override
        )
        warnings += code_warnings
        if errors:
            return {"errors": errors, "warnings": warnings, "facts_only": True}

    # show_drift: surface unreviewed facts as model-tier warnings
    if show_drift and not facts_only and model_file.is_file():
        drift_warnings = _unreviewed_facts_warnings(model, facts)
        warnings += drift_warnings
        for w in drift_warnings:
            if collector:
                collector.model_warning("render_c4", w)

    for old in list(output.glob("c4-*.mmd")) + list(output.glob("c4-*.svg")):
        old.unlink()

    diagrams = {}
    if not model.get("_facts_only"):
        diagrams["c4-context"] = context_diagram(model)
    if model["containers"]:
        diagrams["c4-container"] = container_diagram(model)
    components = component_diagrams(model, facts)
    for stem, _, mermaid, _, _ in components:
        diagrams[stem] = mermaid
    flows = flow_diagrams(model, facts)
    for stem, _, mermaid, _ in flows:
        diagrams[stem] = mermaid
    for entry in code_entries:
        diagrams[entry["stem"]] = entry["mermaid"]
    deployment = deployment_diagram(facts, model)
    if deployment:
        diagrams["c4-deployment"] = deployment

    for stem, mermaid in diagrams.items():
        (output / f"{stem}.mmd").write_text(mermaid, encoding="utf-8")

    rendered = {}
    if svg:
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = {stem: pool.submit(render_svg, output / f"{stem}.mmd", output / f"{stem}.svg") for stem in diagrams}
            rendered = {stem: job.result() for stem, job in jobs.items()}

    block = [BLOCK_START, "", "## Architecture (C4 model)", ""]
    if model.get("_facts_only"):
        block += [
            "> Drawn from code facts only: no `c4-model.json` yet, so people, external purposes, "
            "descriptions and key flows are missing and the System Context level is left out. "
            "Write `c4-model.json` and run `render_c4.py` to complete it.", "",
        ]
    if not model["containers"]:
        block += ["> No containers, data stores or external systems were detected, so there are no C4 diagrams. "
                  "Build the model from the source by hand, or see the dependency graph appendix.", ""]
    elif model["system"].get("description") and not model.get("_facts_only"):
        block += [_clean(model["system"]["description"]), ""]

    if "c4-context" in diagrams:
        block.append(_section("### Level 1: System context", "c4-context", diagrams["c4-context"], rendered.get("c4-context")))
    if "c4-container" in diagrams:
        block.append(_section("### Level 2: Containers", "c4-container", diagrams["c4-container"], rendered.get("c4-container")))
        block += _containers_table(model, facts) + [""]

    if components:
        block += ["### Level 3: Components", "",
                  "For each container: the modules it is built from (when it has several), then the code structure "
                  "inside them (packages or namespaces and the imports between them).", ""]
        for stem, title, mermaid, notes, kind in components:
            block.append(_section(f"#### {title}", stem, mermaid, rendered.get(stem), notes))

    if code_entries:
        block += ["### Level 4: Code", "",
                  "The classes and interfaces of the key components: inheritance, implemented interfaces, "
                  "dependencies inside the component and public methods. Boxes marked external live in another component.", ""]
        for entry in code_entries:
            block.append(_section(f"#### {_clean(entry['title'])}", entry["stem"], entry["mermaid"],
                                  rendered.get(entry["stem"]), code_diagrams.notes(entry), intro=entry["description"]))

    if flows:
        block += ["### Key flows", "", "How a request moves through the system, step by step.", ""]
        for stem, title, mermaid, description in flows:
            block.append(_section(f"#### {_clean(title)}", stem, mermaid, rendered.get(stem), intro=description))

    block += _deployment_section(facts, model, rendered.get("c4-deployment"), deployment)
    block += _endpoints_section(facts, model)
    block += _configuration_section(facts, model)
    block += _inventory_section(facts, model)

    assumptions = _assumptions(model)
    if assumptions:
        block += ["### Assumptions", "", "Not backed by code evidence; confirm with the team:", ""] + assumptions + [""]

    block += ["### C4 files", ""] + [f"- [{stem}.mmd]({stem}.mmd)" for stem in diagrams]
    block += ["- [c4-facts.json](c4-facts.json)"] + (["- [c4-model.json](c4-model.json)"] if model_file.is_file() and not facts_only else [])
    block += ["", BLOCK_END]

    report = output / "ArchitectureReport.md"
    if report.is_file():
        text = report.read_text(encoding="utf-8")
        pattern = re.compile(
            "(?:" + re.escape(BLOCK_START) + "|" + re.escape(OLD_MARKERS[0]) + ").*?(?:"
            + re.escape(BLOCK_END) + "|" + re.escape(OLD_MARKERS[1]) + ")",
            re.DOTALL,
        )
        if pattern.search(text):
            report.write_text(pattern.sub(lambda _: "\n".join(block), text), encoding="utf-8")
        else:
            warnings.append("ArchitectureReport.md has no C4 block; re-run analyze_repository.py")

    return {
        "errors": [],
        "warnings": warnings,
        "diagrams": list(diagrams),
        "svg_failed": [stem for stem, ok in rendered.items() if not ok] if svg else [],
        "facts_only": bool(model.get("_facts_only")),
    }


def main():
    parser = argparse.ArgumentParser(description="Draw the C4 diagrams from c4-facts.json and c4-model.json.")
    parser.add_argument("output", help="Output folder written by analyze_repository.py")
    parser.add_argument("--facts-only", action="store_true", help="Ignore c4-model.json and draw from the facts alone")
    parser.add_argument("--no-svg", action="store_true", help="Skip SVG rendering")
    parser.add_argument("--repo", dest="repo", default=None,
                        help="Override the repository path stored in c4-facts.json (for relocatable output)")
    parser.add_argument("--debug", action="store_true", help="Print the full traceback when an unexpected error occurs")
    args = parser.parse_args()

    result = render(args.output, facts_only=args.facts_only, svg=not args.no_svg, repo_override=args.repo)

    for warning in result["warnings"]:
        print(f"WARNING: {warning}")
    if result["errors"]:
        print("c4-model.json does not match c4-facts.json:", file=sys.stderr)
        for error in result["errors"]:
            print(f"  - {error}", file=sys.stderr)
        sys.exit(1)

    print("Diagrams: " + ", ".join(result["diagrams"]))
    if result["svg_failed"]:
        print("WARNING: SVG rendering failed for " + ", ".join(result["svg_failed"]) + " (needs Node.js and @mermaid-js/mermaid-cli)")


if __name__ == "__main__":
    # --debug is read from argv here: run_cli needs it before main() parses.
    run_cli(main, debug="--debug" in sys.argv)
