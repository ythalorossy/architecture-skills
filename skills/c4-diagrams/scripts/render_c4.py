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

from scripts import svg_render as _sr
from scripts import c4_facts, code_diagrams, generate_docs
from scripts import mermaid_syntax as _ms
from scripts.model_check import ValidationResult, check_structure, load_model


MAX_COMPONENTS = 20
ROW_WIDTH = 6
# Markdown "comments" (empty link definitions) rather than HTML comments: every
# renderer drops them, and none can swallow the content between them.
BLOCK_START = "[//]: # (c4:start)"
BLOCK_END = "[//]: # (c4:end)"
OLD_MARKERS = ("<!-- c4:start -->", "<!-- c4:end -->")

# Every key rendering reads out of c4-facts.json without a default. A missing
# one used to go unnoticed (`endpoints`, `configuration` and `deployment` just
# dropped their report section) or surface as an opaque KeyError
# (`data_stores`), so they are checked once, up front, by name.
REQUIRED_FACTS = (
    "containers", "data_stores", "external_systems", "relationships",
    "endpoints", "deployment", "configuration",
)

# C4 colours, defined once in mermaid_syntax.
STYLES = _ms.flowchart_classdef_lines()


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


ELEMENT_KEYS = ("id", "name", "description", "technology", "type", "evidence", "assumption", "external", "facts")
ELEMENT_TYPES = ("container", "database", "queue")
SUMMARY_KEYS = ("overview", "findings", "recommendations")
# The keys c4-model-reference.md documents, and the only ones anything reads.
# Everything else is dropped on the floor, so say so.
RELATIONSHIP_KEYS = ("from", "to", "description", "technology", "assumption")
FLOW_KEYS = ("id", "name", "description", "steps", "evidence", "assumption")
STEP_KEYS = ("from", "to", "description", "technology", "reply", "async", "note", "evidence", "assumption")


def _did_you_mean(value, candidates):
    """' (did you mean 'x'?)' for the closest candidate, or ''."""
    import difflib
    match = difflib.get_close_matches(str(value), [str(c) for c in candidates], n=1, cutoff=0.75)
    return f" (did you mean {match[0]!r}?)" if match else ""


def _unknown_keys(item, allowed, label, warnings):
    """Warn about every key nothing reads, with the closest documented one."""
    for key in item:
        if key not in allowed:
            warnings.append(f"{label}: unknown key {key!r}{_did_you_mean(key, allowed)}; it is ignored")


def _evidence_problem(entry, repo):
    """Why an evidence entry ("path", "path:12", "path:3-9 (note)") points at nothing, or None."""
    reference = str(entry).split(" (")[0].strip()
    path, line = reference, None
    found = re.fullmatch(r"(.+?):(\d+)(?:-\d+)?", reference)
    if found:
        path, line = found.group(1), int(found.group(2))
    file = repo / path
    if not file.exists():
        return "does not exist in the repository"
    if line is not None and file.is_file():
        try:
            count = len(file.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            return None
        if line > count:
            return f"is past the end of the file ({count} lines)"
    return None


def validate(model, facts, result=None, repo=None):
    """Tiered semantic checks. Returns a ValidationResult.

    `result` (optional) is a ValidationResult from `check_structure`; we
    append to its lists. A new result is created when `result is None`.

    Tiers:
      - unknown relationship/flow ids and duplicate ids -> errors (invalid)
      - facts not covered by the model and not in `excluded` -> drift
      - evidence / assumption missing -> warnings

    `repo` (optional) is the analysed repository; when given, each evidence
    entry is checked to point at an existing file and line.
    """
    if result is None:
        result = ValidationResult(model=model)
    errors = result.errors
    drift = result.drift
    warnings = result.warnings

    def invalid(message):
        errors.append(f"c4-model.json: {message}")

    elements = {}
    for section in ("people", "containers", "external_systems"):
        for index, element in enumerate(model.get(section) or []):
            if not str(element.get("id") or "").strip() or not str(element.get("name") or "").strip():
                invalid(
                    f"{section}[{index}]: every element needs an id and a name "
                    f"({element!r})"
                )
                continue
            if element["id"] in elements:
                invalid(
                    f"{section}[{index}]: duplicate id {element['id']!r}"
                )
            elements[element["id"]] = section
            if not element.get("evidence") and not element.get("assumption"):
                warnings.append(f"{element['id']}: no evidence and not marked as an assumption")
            _unknown_keys(element, ELEMENT_KEYS, element["id"], warnings)
            if "type" in element and element["type"] not in ELEMENT_TYPES:
                warnings.append(f"{element['id']}: unknown type {element['type']!r}"
                                f"{_did_you_mean(element['type'], ELEMENT_TYPES)}; use container, database or queue")
            if repo is not None:
                for entry in element.get("evidence") or []:
                    problem = _evidence_problem(entry, Path(repo))
                    if problem:
                        warnings.append(f"{element['id']}: evidence {entry!r} {problem}")

    system_name = (model.get("system") or {}).get("name")
    if system_name is None or system_name == "":
        invalid("system.name is missing")

    fact_ids = [f["id"] for kind in ("containers", "data_stores", "external_systems") for f in facts[kind]]
    store_ids = {f["id"] for f in facts["data_stores"]}
    covered_by = {}
    for section in ("containers", "external_systems"):
        for element in model.get(section) or []:
            if "id" not in element:
                continue
            if section == "external_systems":
                for fact in _covers(element):
                    if fact in store_ids:
                        # A store the repository runs is a container of the
                        # system, not a system someone else owns.
                        warnings.append(
                            f"{element['id']}: {fact} is a data store found in this repository; "
                            'move it to containers with "type": "database", and add "external": true '
                            "if the system does not own it"
                        )
            for fact in element.get("facts") or []:
                if fact not in fact_ids:
                    warnings.append(f"{element['id']}: facts lists {fact!r}, which is not in c4-facts.json"
                                    f"{_did_you_mean(fact, fact_ids)}")
            for fact in _covers(element):
                if fact in fact_ids:
                    covered_by.setdefault(fact, []).append(element["id"])
    for fact, owners in covered_by.items():
        if len(owners) > 1:
            names = sorted(owners)
            listed = f"both {names[0]} and {names[1]}" if len(names) == 2 else ", ".join(names)
            # _container_lookup keeps the last element that lists the fact.
            warnings.append(f"{fact} is covered by {listed}; it is drawn once, as {owners[-1]}")
    for item in model.get("excluded") or []:
        if not item.get("id"):
            continue
        if not str(item.get("reason") or "").strip():
            warnings.append(f"excluded {item['id']}: give a reason, so readers know why it is left out")
        if item["id"] not in fact_ids:
            warnings.append(f"excluded {item['id']} is not in c4-facts.json{_did_you_mean(item['id'], fact_ids)}")
    covered = {fact for section in ("containers", "external_systems") for e in model.get(section) or [] for fact in _covers(e)}
    covered |= {item["id"] for item in model.get("excluded") or []}
    for kind in ("containers", "data_stores", "external_systems"):
        for fact in facts[kind]:
            if fact["id"] not in covered:
                drift.append(
                    f"{fact['id']} ({fact['name']}) was found in the code but is not in the model; "
                    "add it (or list it in `facts` of an element) or put it in `excluded` with a reason"
                )

    component_ids = all_component_ids(model, facts)
    components = {c for ids in component_ids.values() for c in ids}

    pairs = {}
    for index, relationship in enumerate(model.get("relationships") or []):
        _unknown_keys(relationship, RELATIONSHIP_KEYS, f"relationships[{index}]", warnings)
        pairs.setdefault((relationship.get("from"), relationship.get("to")), []).append(index)
        for end in ("from", "to"):
            value = relationship.get(end)
            if value not in elements:
                # A component only exists inside a container, so it can be a
                # flow step but never an end of a Level 2 relationship.
                hint = (
                    "; it is a component, so use a flow step to show calls inside a container"
                    if value in components else _did_you_mean(value, elements)
                )
                invalid(
                    f"relationships[{index}]: {relationship.get('from')!r} -> "
                    f"{relationship.get('to')!r}: unknown {end!r} id {value!r}{hint}"
                )

    for container_id, descriptions in (model.get("components") or {}).items():
        if elements.get(container_id) != "containers":
            invalid(
                f"components[{container_id!r}]: {container_id!r} is not a container id"
                f"{_did_you_mean(container_id, [e for e, s in elements.items() if s == 'containers'])}"
            )
            continue
        for component in descriptions:
            if component not in component_ids.get(container_id, set()):
                warnings.append(f"components.{container_id}: {component!r} is not a component of that container; its description is ignored")

    for (source, target), indexes in pairs.items():
        if len(indexes) > 1:
            # _merge_relationships keeps one edge per (from, to), so the second
            # description is never drawn.
            times = "twice" if len(indexes) == 2 else f"{len(indexes)} times"
            listed = ", ".join(f"relationships[{index}]" for index in indexes)
            warnings.append(f"{source} -> {target} is listed {times} ({listed}); they are drawn as one arrow")

    known = set(elements) | components
    for flow_index, flow in enumerate(model.get("flows") or []):
        _unknown_keys(flow, FLOW_KEYS, f"flows[{flow_index}]", warnings)
        if not flow.get("name") or not flow.get("steps"):
            invalid(
                f"flows[{flow_index}]: every flow needs a name and steps "
                f"({flow.get('id') or flow.get('name')!r})"
            )
            continue
        label = flow.get("id") or flow["name"]
        # A flow is the most interpreted part of the model: which containers
        # exist comes from the code, the order they talk in comes from reading
        # it. Say so when nothing backs that reading, as for any element.
        proven = flow.get("evidence") or any(step.get("evidence") for step in flow["steps"])
        if not proven and not flow.get("assumption"):
            warnings.append(f"flow {label!r} ({flow['name']}): no evidence and not marked as an assumption")
        if repo is not None:
            for entry in flow.get("evidence") or []:
                problem = _evidence_problem(entry, Path(repo))
                if problem:
                    warnings.append(f"flow {label!r}: evidence {entry!r} {problem}")

        for number, step in enumerate(flow["steps"], 1):
            _unknown_keys(step, STEP_KEYS, f"flows[{flow_index}].steps[{number - 1}]", warnings)
            if repo is not None:
                for entry in step.get("evidence") or []:
                    problem = _evidence_problem(entry, Path(repo))
                    if problem:
                        warnings.append(f"flow {label!r} step {number}: evidence {entry!r} {problem}")
            for end in ("from", "to"):
                if step.get(end) not in known:
                    invalid(
                        f"flows[{flow_index}].steps[{number-1}]: flow {flow['name']!r} step "
                        f"{number}: unknown {end} {step.get(end)!r}{_did_you_mean(step.get(end), known)} "
                        "(use a person, container or external system id, or a component id from c4-facts.json)"
                    )

    for key in (model.get("summary") or {}):
        if key not in SUMMARY_KEYS:
            warnings.append(f"summary: unknown key {key!r}{_did_you_mean(key, SUMMARY_KEYS)}; it is ignored")

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

    return result


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


COVERAGE_LINE = ("Coverage: facts {}/{}, containers described {}/{}, "
                 "components described {}/{}, people {}, flows {}, code {}")


def _coverage(model, facts, result):
    """How much of the judgement work the model carries.

    `validate` answers "is this model consistent?"; this answers "is it
    finished?" -- a model can be `ok` and say nothing.
    """
    fact_ids = {f["id"] for kind in ("containers", "data_stores", "external_systems") for f in facts[kind]}
    containers = [c for c in model.get("containers") or [] if c.get("id")]
    component_ids = all_component_ids(model, facts)
    return {
        "facts": [len(fact_ids) - len(result.drift), len(fact_ids)],
        "containers_described": [sum(1 for c in containers if str(c.get("description") or "").strip()),
                                 len(containers)],
        "components_described": [sum(len(d) for d in (model.get("components") or {}).values()),
                                 sum(len(ids) for ids in component_ids.values())],
        "people": len(model.get("people") or []),
        "flows": len(model.get("flows") or []),
        "code": len(model.get("code") or []),
    }


# ---------- mermaid ----------

def _clean(text):
    """Escape text for plain (non-markdown) flowchart labels using entity codes."""
    return _ms.label_text("flowchart_plain", str(text))


def _prose(text):
    """Report text: Markdown prose, so plain < and >, never Mermaid entity codes."""
    return str(text)


#: Line break inside a label. Plain labels take no raw newline, and it has to
#: go in after escaping, which turns a literal < into an entity code.
BR = "<br/>"


def _wrap(text, width=34):
    return BR.join(textwrap.wrap(_clean(text), width)) if text else ""


def _label(name, kind, description=""):
    """Build a label for a C4 element node.

    Plain, not a mermaid markdown string ("`…`"). A markdown string makes
    mermaid parse the label as Markdown, and ordinary code names are full of
    its metacharacters: ``user_service`` loses the underscore and ``__main__``
    turns bold. Escaping them does not help on the SVG path, where the renderer
    drops the escapes and the characters with them. A plain label parses no
    Markdown, so every character survives. The name is no longer bold.
    """
    lines = [_clean(name), f"[{_clean(kind)}]"]
    if description:
        lines.append(_wrap(description))
    return '"' + BR.join(lines) + '"'


def _edge_label(description, technology=""):
    text = _wrap(description, 28) if description else ""
    if technology:
        text += (BR if text else "") + f"[{_clean(technology)}]"
    return f'|"{text}"|' if text else ""


def _with_title(mermaid, title):
    """The diagram with a front-matter ``title`` (see mermaid_syntax.with_title)."""
    return _ms.with_title(mermaid, title)


class Diagram:
    def __init__(self):
        self.lines = []
        self.classes = {}
        self._ids = _ms.IdAllocator("flowchart")

    def id(self, key):
        """Unique, readable Mermaid id for key within this diagram."""
        return self._ids.id(key)

    def internal(self, name):
        """Id for an internal node (boundary, module box) in this diagram."""
        return self._ids.internal(name)

    def __contains__(self, key):
        return key in self._ids

    def node(self, key, label, cls, shape="rect", indent="    "):
        open_, close = {"rect": ("[", "]"), "db": ("[(", ")]"), "round": ("(", ")")}[shape]
        self.lines.append(f"{indent}{self.id(key)}{open_}{label}{close}")
        self.classes.setdefault(cls, []).append(self.id(key))

    def edge(self, source, target, label="", dashed=False):
        arrow = "-.->" if dashed else "-->"
        self.lines.append(f"    {self.id(source)} {arrow}{label} {self.id(target)}")

    def text(self, boundaries=()):
        out = ["flowchart TB"] + self.lines + ["    " + s for s in STYLES]
        for cls, ids in self.classes.items():
            out.append(f"    class {','.join(ids)} {cls}")
        for boundary in boundaries:
            out.append(f"    style {boundary} {_ms.boundary_style()}")
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


# Descriptions that only say "there is a link" (compose depends_on, defaults).
_GENERIC_DESCRIPTIONS = {"", "depends on", "uses"}


def _merge_relationships(relationships):
    """
    One edge per (from, to). The first specific description wins over a
    generic one ("Depends on" from compose loses to "Reads/writes" found in
    the code), and the technologies of all records are combined.
    """
    merged = {}
    for r in relationships:
        key = (r["from"], r["to"])
        if key[0] == key[1]:
            continue
        current = merged.get(key)
        if current is None:
            merged[key] = dict(r)
            continue
        technologies = [t for t in (current.get("technology"), r.get("technology")) if t]
        if _is_generic(current) and not _is_generic(r):
            # Reassigning an existing key keeps the edge where it was.
            merged[key] = current = dict(r)
        combined = []
        for tech in technologies:
            for part in str(tech).split(","):
                part = part.strip()
                if part and part not in combined:
                    combined.append(part)
        if combined:
            current["technology"] = ", ".join(combined)
    return list(merged.values())


def _is_generic(relationship):
    return (relationship.get("description") or "").strip().lower() in _GENERIC_DESCRIPTIONS


def context_diagram(model):
    d = Diagram()
    system = model["system"]
    inside = {c["id"] for c in model["containers"] if not c.get("external")}
    outside = {c["id"]: c for c in model["containers"] if c.get("external")}

    for person in model["people"]:
        _element_node(d, person, "people")
    system_id = _ms.IdAllocator.internal_key("system")
    d.node(system_id, _label(system["name"], "Software System", system.get("description")), "system")
    for external in model["external_systems"]:
        _element_node(d, external, "external_systems")
    for container in outside.values():
        d.node(container["id"], _label(container["name"], "Software System", container.get("description")), "external")

    lift = lambda node: system_id if node in inside else node
    edges = _merge_relationships([
        {**r, "from": lift(r["from"]), "to": lift(r["to"])} for r in model["relationships"]
    ])
    for r in edges:
        d.edge(r["from"], r["to"], _edge_label(r.get("description"), r.get("technology")))
    return _with_title(d.text(), f"{system['name']} \u00b7 System context")


def container_diagram(model):
    d = Diagram()
    for person in model["people"]:
        _element_node(d, person, "people")

    boundary = d.internal("boundary")
    d.lines.append(f'    subgraph {boundary}["{_clean(model["system"]["name"])} [Software System]"]')
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
    return _with_title(d.text([boundary]), f"{model['system']['name']} \u00b7 Containers")


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


def _component_label(node, info, short):
    """The text drawn in a component box."""
    return (info.get("label") or short[node]).replace(" (files)", " (root files)")


def _drawn_graph(graph):
    """What a component-style diagram of ``graph`` shows: box labels and the
    edges between them.

    The node keys are left out on purpose. A container's modules and the code
    structure inside them are keyed differently (``internal/store`` against
    ``internal/store::internal/store``) while drawing the very same picture,
    and that is what makes one of the two views worth skipping.
    """
    nodes = graph.get("nodes") or {}
    short = _short_names(list(nodes))
    labels = {node: _component_label(node, info, short) for node, info in nodes.items()}
    edges = {
        (labels[source], labels[target])
        for source, targets in (graph.get("edges") or {}).items() if source in labels
        for target in targets if target in labels
    }
    return set(labels.values()), edges


def _transitive_reduction(edges):
    """Drop an edge only while another path still connects its ends (safe with cycles)."""
    current = {a: list(targets) for a, targets in edges.items()}

    def reachable(start, goal, skip):
        # The skipped edge must stay out of every step: through a cycle the
        # search can come back to `start` and would otherwise follow it.
        seen, stack = set(), [start]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            for target in current.get(node, []):
                if (node, target) == skip:
                    continue
                if target == goal:
                    return True
                stack.append(target)
        return False

    for a in sorted(current):
        for b in list(current[a]):
            if reachable(a, b, (a, b)):
                current[a].remove(b)
    return current


def _hubs(nodes, all_edges):
    """
    (components most others use, the note that says so), or ([], None).

    Counts every dependency, not only the ones left after hiding shortcuts:
    reduction removes most of the edges into a widely used component, so a
    hub is invisible in the reduced graph.
    """
    indegree = {n: 0 for n in nodes}
    for targets in all_edges.values():
        for target in targets:
            if target in indegree:
                indegree[target] += 1
    threshold = max(3, len(nodes) // 2)
    shared = [n for n, count in indegree.items() if count >= threshold]
    if not shared:
        return [], None
    return shared, (
        "Used by most other components, drawn in the Shared box without their incoming edges: "
        + ", ".join(f"{n} ({indegree[n]})" for n in shared) + "."
    )


def _dependency_order(nodes, edges):
    """Every node once, a component after the ones it uses, ties in name order.

    A cycle has no such order; its members follow in name order. The result
    only depends on the names and the edges, never on the order the nodes
    arrived in, so the parts built from it are stable between runs.
    """
    uses = {n: {t for t in edges.get(n, []) if t in nodes and t != n} for n in nodes}
    done, order = set(), []
    while len(order) < len(nodes):
        ready = sorted(n for n in uses if n not in done and uses[n] <= done)
        if not ready:  # only cycles left
            ready = sorted(n for n in uses if n not in done)
        done.update(ready)
        order += ready
    return order


def _flat_groups(nodes, edges):
    """Sub-groups of one flat group of components, and whether they are named.

    A container whose components share no folder still has too many of them
    to draw at once. They are split by the first path segment of the name
    when that says something ("src/api/books" and "src/ui/cart" are a folder
    apart), and otherwise into chunks of MAX_COMPONENTS in dependency order.
    Chunk keys are numbers a reader can learn nothing from, which is what the
    second return value says.
    """
    short = _short_names(list(nodes))
    order = _dependency_order(nodes, edges)
    by_segment = {}
    for node in order:
        head = re.match(r"(.+?)[./]", short[node])
        by_segment.setdefault(head.group(1) if head else "(root)", []).append(node)
    if len(by_segment) > 1:
        return _capped(by_segment), True
    return ({f"part {index // MAX_COMPONENTS + 1}": order[index:index + MAX_COMPONENTS]
             for index in range(0, len(order), MAX_COMPONENTS)}, False)


def _capped(groups):
    """The same groups, with any group above MAX_COMPONENTS cut into numbered chunks."""
    out = {}
    for group, members in groups.items():
        if len(members) <= MAX_COMPONENTS:
            out[group] = members
            continue
        chunks = -(-len(members) // MAX_COMPONENTS)
        for index in range(chunks):
            out[f"{group} ({index + 1} of {chunks})"] = members[index * MAX_COMPONENTS:(index + 1) * MAX_COMPONENTS]
    return out


def _component_views(graph, overview=True, full_list="the dependency graph appendix"):
    """
    Split one container's components into readable views: [(suffix, title, nodes, edges, notes)].
    Shortcut edges are hidden when the graph is dense; above MAX_COMPONENTS nodes the
    view is split into parts of at most MAX_COMPONENTS (by folder/module, or, when there
    is only one, by the next path segment or in dependency order), and components most
    others use are moved to a "shared" box.
    """
    nodes = graph["nodes"]
    edges = graph["edges"]
    all_edges = edges
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

    shared = []
    if len(nodes) > MAX_COMPONENTS and len(groups) < 2:
        # One flat group: the components everyone uses are the only structure
        # it has, so they are found before it is cut into parts.
        shared, hub_note = _hubs(nodes, all_edges)
        if shared:
            notes.append(hub_note)
            edges = {n: [t for t in targets if t not in shared] for n, targets in edges.items()}
        groups, named = _flat_groups(nodes, edges)
        overview = overview and named
    elif len(nodes) > MAX_COMPONENTS:
        # Folders, but one of them can still be too large to read on its own.
        rank = {node: index for index, node in enumerate(_dependency_order(nodes, edges))}
        groups = _capped({g: sorted(m, key=rank.__getitem__) for g, m in groups.items()})

    if len(nodes) > MAX_COMPONENTS:
        group_of = {n: g for g, members in groups.items() for n in members}
        group_edges = {}
        # From the raw edges, not the reduced ones: hiding A → C is only
        # readable when A → B → C is drawn beside it, and the folder overview
        # draws neither, so a reduced edge would silently drop a folder arrow.
        for source, targets in all_edges.items():
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
        part_of = {n: index for index, pack in enumerate(packs, 1) for _, members in pack for n in members}
        for index, pack in enumerate(packs, 1):
            members = [n for _, m in pack for n in m]
            member_set = set(members)
            first_notes = [] if overview or index > 1 else notes + [f"{len(nodes)} components, drawn in {len(packs)} parts."]
            view_nodes = {n: ({**nodes[n], "shared": True} if n in shared else nodes[n]) for n in members}
            view_edges = {}
            for n in members:
                view_edges[n] = []
                for target in edges.get(n, []):
                    if target not in member_set:
                        # Drawn elsewhere: keep the dependency, with a stub saying where.
                        where = f"in part {part_of[target]}" if target in part_of else "in the overview"
                        view_nodes.setdefault(target, {**nodes[target], "stub": where})
                    view_edges[n].append(target)
            views.append((
                f"-part{index}",
                ", ".join(sorted(g for g, _ in pack)) if len(pack) <= 3 else f"part {index} of {len(packs)}",
                view_nodes,
                view_edges,
                first_notes,
            ))
        return views

    return [("", "", nodes, edges, notes)]


def _container_lookup(model):
    by_fact = {}
    for section in ("containers", "external_systems"):
        for element in model[section]:
            for fact in _covers(element):
                by_fact[fact] = element
    return by_fact


def _context_nodes(diagram, model, container, boundary_key):
    """Draw the people, containers and systems this container talks to, around its boundary.

    Level 2 shows who calls the container and what it calls; without the
    same neighbours on Level 3 the two levels contradict each other. Only
    direct model relationships are drawn — the facts say which component
    uses a store, and those edges are already on the diagram, so a neighbour
    already drawn is left alone.
    """
    by_id = {}
    for section in ("people", "containers", "external_systems"):
        for element in model.get(section) or []:
            by_id.setdefault(element.get("id"), (element, section))
    for r in _merge_relationships(model.get("relationships") or []):
        if r["from"] == container["id"]:
            other, inbound = r["to"], False
        elif r["to"] == container["id"]:
            other, inbound = r["from"], True
        else:
            continue
        found = by_id.get(other)
        if found is None or other in diagram:
            continue
        element, section = found
        if section == "containers" and element.get("external"):
            diagram.node(element["id"], _label(element["name"], "Software System", element.get("description")), "external")
        else:
            _element_node(diagram, element, section)
        label = _edge_label(r.get("description"), r.get("technology"))
        ends = (other, boundary_key) if inbound else (boundary_key, other)
        diagram.edge(*ends, label)


def _graph_diagram(model, facts, container, container_fact, title, nodes, edges, texts, usage_key):
    """One component-style diagram: nodes inside the container boundary (grouped by module when
    there are several), edges between them, and the stores/external systems they use."""
    by_fact = _container_lookup(model)
    relationship_text = {(r["from"], r["to"]): r for r in model["relationships"]}
    d = Diagram()
    short = _short_names(list(nodes))
    boundary_key = _ms.IdAllocator.internal_key("boundary")
    boundary = d.id(boundary_key)
    d.lines.append(f'    subgraph {boundary}["{_clean(title)} [Container]"]')
    regular = [n for n, info in nodes.items() if not info.get("shared") and not info.get("stub")]
    shared = [n for n, info in nodes.items() if info.get("shared")]
    stubs = [n for n, info in nodes.items() if info.get("stub")]

    def label_of(node):
        return _component_label(node, nodes[node], short)

    modules = {}
    for node in regular:
        modules.setdefault(nodes[node].get("module"), []).append(node)
    boxes = []
    if usage_key == "used_by_code" and len(modules) > 1:
        for module, members in sorted(modules.items(), key=lambda m: str(m[0])):
            box = d.internal(f"module_{module}")
            boxes.append(box)
            d.lines.append(f'        subgraph {box}["{_clean(module)}"]')
            for node in members:
                d.node(node, _label(label_of(node), "Component", texts.get(node, "")), "component", indent="            ")
            d.lines.append("        end")
    else:
        for node in regular:
            d.node(node, _label(label_of(node), "Component", texts.get(node, "")), "component", indent="        ")
    if shared:
        d.lines.append(f'        subgraph {d.internal("shared")}["Shared"]')
        for node in shared:
            d.node(node, _label(label_of(node), "Component", texts.get(node, "")), "shared", indent="            ")
        d.lines.append("        end")
    d.lines.append("    end")
    # Components drawn in another part of a split view.
    for node in stubs:
        d.node(node, _label(label_of(node), f"Component, {nodes[node]['stub']}"), "shared")

    for source, targets in edges.items():
        for target in targets:
            if source in nodes and target in nodes:
                d.edge(source, target, dashed=bool(nodes[target].get("stub")))

    # A component nothing points at shares the first row with every other
    # one, so a container with many of them comes out as a single very wide
    # strip. Invisible links stack them in rows of ROW_WIDTH instead.
    if not boxes:
        targeted = {t for targets in edges.values() for t in targets}
        roots = [n for n in regular if n not in targeted]
        for upper, lower in zip(roots, roots[ROW_WIDTH:]):
            d.lines.append(f"    {d.id(upper)} ~~~ {d.id(lower)}")

    for kind in ("data_stores", "external_systems"):
        for fact in facts[kind]:
            element = by_fact.get(fact["id"])
            users = [n for n in (fact.get(usage_key) or {}).get(container_fact["id"], [])
                     if n in nodes and not nodes[n].get("stub")]
            if element is None or not users:
                continue
            if element["id"] not in d:
                section = "containers" if element in model["containers"] else "external_systems"
                _element_node(d, element, section)
            r = relationship_text.get((container["id"], element["id"]), {})
            for user in users:
                d.edge(user, element["id"], _edge_label(r.get("description", "Uses"), r.get("technology")))

    _context_nodes(d, model, container, boundary_key)

    out = d.text([boundary])
    for box in boxes:
        out += f"    style {box} {_ms.folder_style()}\n"
    return out


SHARED_STEM = "c4-component-shared"
# Key of the one node a container's Level 3 collapses its shared libraries
# into. Not a component name: no node can be called this.
SHARED_NODE = "(shared libraries)"


def _shared_libraries(facts, by_fact):
    """
    ``{component: [container id, ...]}`` for every component more than one
    container is built from.

    A library several containers compile in is part of all of them, so it used
    to be redrawn in every Level 3 diagram. Those are the components that get
    one view of their own instead.
    """
    users = {}
    for container_fact in facts["containers"]:
        if by_fact.get(container_fact["id"]) is None:
            continue  # excluded in the model
        for node in ((container_fact.get("components") or {}).get("nodes") or {}):
            users.setdefault(node, []).append(container_fact["id"])
    return {node: ids for node, ids in sorted(users.items()) if len(ids) > 1}


def _collapse_shared(components, shared):
    """
    (the container's component graph with the shared libraries replaced by one
    node, the names replaced). An edge into a library becomes an edge into that
    node, which is drawn as a stub pointing at the shared view.
    """
    mine = [node for node in components.get("nodes", {}) if node in shared]
    if not mine:
        return components, []

    nodes = {node: info for node, info in components["nodes"].items() if node not in shared}
    edges = {}
    for node in nodes:
        targets = []
        for target in components.get("edges", {}).get(node, []):
            target = SHARED_NODE if target in shared else target
            if target not in targets and target != node:
                targets.append(target)
        edges[node] = targets

    nodes[SHARED_NODE] = {
        "group": "",
        "label": f"Shared libraries ({len(mine)})",
        "stub": f"drawn once in {SHARED_STEM}.mmd",
    }
    edges[SHARED_NODE] = []
    return {"nodes": nodes, "edges": edges}, mine


def _shared_edges(facts, shared):
    """``{library: [library, ...]}``: the dependencies between the shared libraries."""
    edges = {}
    for container_fact in facts["containers"]:
        components = container_fact.get("components") or {}
        for source, targets in (components.get("edges") or {}).items():
            if source not in shared:
                continue
            for target in targets:
                if target in shared and target != source:
                    edges.setdefault(source, set()).add(target)
    return {source: sorted(targets) for source, targets in sorted(edges.items())}


def _shared_diagram(model, facts, shared, by_fact, texts, title):
    """The shared libraries, the edges between them, and the containers that use them."""
    d = Diagram()
    short = _short_names(list(shared))
    boundary_key = _ms.IdAllocator.internal_key("boundary")
    boundary = d.id(boundary_key)
    d.lines.append(f'    subgraph {boundary}["{_clean(title)}"]')
    for node in shared:
        d.node(node, _label(short[node], "Component", texts.get(node, "")), "component", indent="        ")
    d.lines.append("    end")

    for container_fact in facts["containers"]:
        container = by_fact.get(container_fact["id"])
        if container is None:
            continue
        components = container_fact.get("components") or {}
        own = [node for node in components.get("nodes", {}) if node not in shared]
        used = {
            target
            for node in (own or components.get("nodes", {}))
            for target in components.get("edges", {}).get(node, [])
            if target in shared
        }
        if not used:
            # Nothing of its own points at a library: it is built from them.
            used = {node for node in components.get("nodes", {}) if node in shared}
        if not used:
            continue
        if container["id"] not in d:
            _element_node(d, container, "containers")
        for node in sorted(used):
            d.edge(container["id"], node, _edge_label("Uses", ""))

    for source, targets in _shared_edges(facts, shared).items():
        for target in targets:
            d.edge(source, target)

    return _with_title(d.text([boundary]), title)


def component_diagrams(model, facts):
    """
    [(file stem, title, mermaid, notes, kind)] per container: its modules (when it has
    at least two) and the code structure inside them (packages/namespaces).

    A component more than one container is built from is drawn once, in a view
    of its own, and each container's Level 3 collapses the ones it uses into a
    single node. A container left with fewer than two nodes that way is built
    only from shared libraries and gets no module view: the shared one has it.
    """
    by_fact = _container_lookup(model)
    descriptions = model.get("components") or {}
    results = []

    shared_users = _shared_libraries(facts, by_fact)

    for container_fact in facts["containers"]:
        container = by_fact.get(container_fact["id"])
        if container is None:
            continue  # excluded in the model
        texts = descriptions.get(container["id"]) or {}

        declared = container_fact.get("components") or {}
        components, collapsed = _collapse_shared(declared, shared_users) if shared_users else (declared, [])
        has_modules = len(components.get("nodes", {})) >= 2
        if has_modules:
            views = _component_views(components)
            for index, (suffix, subtitle, nodes, edges, notes) in enumerate(views):
                if index == 0 and collapsed:
                    names = ", ".join(sorted(collapsed))
                    notes = notes + [
                        f"{names} is shared with another container and drawn once in {SHARED_STEM}.mmd."
                        if len(collapsed) == 1 else
                        f"{len(collapsed)} components are shared with other containers and drawn once "
                        f"in {SHARED_STEM}.mmd: {names}."
                    ]
                title = container["name"] + (f" / {subtitle}" if subtitle else "")
                stem = f"c4-component-{container['id']}{suffix}"
                mermaid = _with_title(
                    _graph_diagram(model, facts, container, container_fact, title, nodes, edges, texts, "used_by_components"),
                    title)
                results.append((stem, title, mermaid, notes, "modules"))

        code = container_fact.get("code_components") or {}
        # A module holding one package named after it draws the same boxes and
        # the same arrows as the module view above; a second copy of a diagram
        # is not a second level of detail, so it is left out.
        echoes_modules = has_modules and _drawn_graph(code) == _drawn_graph(declared)
        if len(code.get("nodes", {})) >= 2 and not echoes_modules:
            for suffix, subtitle, nodes, edges, notes in _component_views(
                code, overview=not has_modules, full_list="c4-facts.json (`code_components`)"
            ):
                title = f"{container['name']} · code structure" + (f" / {subtitle}" if subtitle else "")
                stem = f"c4-structure-{container['id']}{suffix}"
                mermaid = _with_title(
                    _graph_diagram(model, facts, container, container_fact, title, nodes, edges, texts, "used_by_code"),
                    title)
                results.append((stem, title, mermaid, notes, "code"))

    if shared_users:
        title = f"{model['system']['name']} · Shared libraries"
        texts = {
            node: text
            for container_id, described in (model.get("components") or {}).items()
            for node, text in described.items()
            if node in shared_users
        }
        note = (
            "Components used by more than one container, drawn once here instead of in each "
            "container's diagram: "
            + "; ".join(f"{node} ({', '.join(users)})" for node, users in shared_users.items())
            + "."
        )
        results.append((
            SHARED_STEM,
            title,
            _shared_diagram(model, facts, shared_users, by_fact, texts, title),
            [note],
            "modules",
        ))

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
    """Message text for a sequence diagram: single-pass escape of # and ;."""
    return _ms.label_text("sequence_msg", str(text)).replace("\n", " ")


def _unproven(flow, step):
    """
    True when a flow step is a reading of the code rather than a trace of it.

    Its own evidence settles it either way. Without evidence it is unproven
    when the step or the whole flow is marked an assumption.
    """
    if step.get("evidence"):
        return False
    return bool(step.get("assumption") or flow.get("assumption"))


def flow_diagrams(model, facts):
    """[(stem, title, mermaid, description)] for each key flow in the model, as sequence diagrams."""
    participants = _participants(model, facts)
    results = []
    for index, flow in enumerate(model.get("flows") or [], 1):
        used = []
        for step in flow["steps"]:
            for end in (step["from"], step["to"]):
                if end not in used:
                    used.append(end)
        alloc = _ms.IdAllocator("sequence")
        safe = {node: alloc.id(node) for node in used}
        lines = ["sequenceDiagram"]
        for node in used:
            label, kind = participants.get(node, (node, "participant"))
            lines.append(f'    {kind} {safe[node]} as {_ms.label_text("sequence_alias", str(label))}')
        for step in flow["steps"]:
            arrow = "-->>" if step.get("reply") else ("-)" if step.get("async") else "->>")
            text = _seq_text(step.get("description", ""))
            if _unproven(flow, step):
                # Nothing in the code backs this step: say so where it is read.
                text += " (?)"
            if step.get("technology"):
                text += f" [{_seq_text(step['technology'])}]"
            lines.append(f"    {safe[step['from']]}{arrow}{safe[step['to']]}: {text or ' '}")
            if step.get("note"):
                lines.append(f"    Note over {safe[step['to']]}: {_seq_text(step['note'])}")
        slug = re.sub(r"[^a-z0-9]+", "-", (flow.get("id") or flow["name"]).lower()).strip("-") or str(index)
        results.append((f"c4-flow-{slug}", flow["name"],
                        _with_title("\n".join(lines) + "\n", flow["name"]), flow.get("description", "")))
    return results


def deployment_diagram(facts, model):
    """Compose services as a deployment view: services, images/builds, published ports, depends_on."""
    services = (facts.get("deployment") or {}).get("compose") or []
    if not services:
        return None
    by_fact = _container_lookup(model)
    d = Diagram()
    host = d.internal("host")
    d.lines.append(f'    subgraph {host}["Docker host [docker compose]"]')
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
        # The same image table the facts use, so a store is a store in every view.
        store = any(key in image.split(":")[0].lower() for key, _ in c4_facts.COMPOSE_STORES)
        lines = [_clean(name), "[Container instance]"] + [_wrap(detail)] + ([f"ports {_clean(ports)}"] if ports else [])
        label = '"' + BR.join(l for l in lines if l) + '"'
        d.node(f"svc:{service['name']}", label, "container", "db" if store else "rect", indent="        ")
    d.lines.append("    end")
    for service in services:
        for dependency in service.get("depends_on") or []:
            if any(s["name"] == dependency for s in services):
                d.edge(f"svc:{service['name']}", f"svc:{dependency}", _edge_label("depends on"))
    return _with_title(d.text([host]), f"{model['system']['name']} \u00b7 Deployment (docker compose)")


# ---------- output ----------

def _section(title, stem, mermaid, svg_ok, notes=(), intro="", svg_error=None):
    lines = [title, ""]
    if intro:
        lines += [_prose(intro), ""]
    notes = list(notes)
    if svg_error:
        # Without this the reader sees Mermaid source where the other
        # diagrams have a picture, and nothing says the image is missing.
        status, message = svg_error
        notes.append(f"This diagram did not render to an image ({status}"
                     + (f": {_prose(message)}" if message else "")
                     + "). The Mermaid source is below.")
    lines += [f"> {note}" for note in notes] + ([""] if notes else [])
    if svg_ok:
        lines += [f"![{stem}]({stem}.svg)", "", "<details>", "<summary>Mermaid source</summary>", "",
                  "```mermaid", mermaid.rstrip(), "```", "", "</details>"]
    else:
        lines += ["```mermaid", mermaid.rstrip(), "```"]
    return "\n".join(lines) + "\n"


#: The legend: (symbol kind, shape, meaning). A row is written only when the
#: diagrams in this report actually draw that symbol, so the Key never
#: explains a shape the reader cannot find.
_KEY_ROWS = (
    ("person", "Dark blue rounded box", "**Person** — a user or a role outside the system."),
    ("system", "Blue box (Level 1)", "**Software system** — the system this report describes."),
    ("container", "Blue box", "**Container** — an application or service that runs on its own."),
    ("database", "Blue cylinder", "**Data store** — a database, cache or queue."),
    ("component", "Light blue box", "**Component** — a module, package or namespace inside one container."),
    ("shared", "Pale dashed box", "Used by most of the other components, drawn in another part of the same view, or shared with another container and drawn once in the shared-libraries view."),
    ("external", "Grey box", "**External system** — run by someone else."),
    ("boundary", "Dashed grey outline", "The system or the container the diagram is about."),
    ("arrow", "Solid arrow", "A dependency or a call, labelled with what it does and the technology it uses."),
    ("dashed", "Dashed arrow", "A dependency on a component drawn in another part of the same view."),
)

_KEY_CLASSES = ("person", "system", "container", "component", "external", "shared")


def _key_symbols(diagrams):
    """Which `_KEY_ROWS` the drawn diagrams use.

    Read off the diagrams themselves rather than the model: the palette is
    declared in every flowchart whether or not a box uses it, so only the
    `class` lines, the shapes and the arrow styles say what is really there.
    """
    used = set()
    for mermaid in diagrams:
        if "flowchart TB" not in mermaid:
            # Level 4 class diagrams style each box on its own line.
            for kind in ("component", "shared"):
                if f"fill:{_ms.C4_PALETTE[kind]}" in mermaid:
                    used.add(kind)
            continue
        if "stroke-dasharray:6 4" in mermaid:
            used.add("boundary")
        for line in mermaid.splitlines():
            words = line.split()
            if len(words) == 3 and words[0] == "class" and words[2] in _KEY_CLASSES:
                used.add(words[2])
            if "[(" in line:
                used.add("database")
            if "-.->" in line:
                used.add("dashed")
            elif "-->" in line:
                used.add("arrow")
    return used


def _key_section(diagrams):
    """The one Key block for the report: the shapes and lines these diagrams use."""
    used = _key_symbols(diagrams)
    rows = [f"| {symbol} | {meaning} |" for kind, symbol, meaning in _KEY_ROWS if kind in used]
    if not rows:
        return []
    return ["### Diagram key", "", "What the shapes and lines in the diagrams below mean.", "",
            "| Symbol | Meaning |", "|---|---|"] + rows + [""]


def _cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def _assumptions(model):
    """Everything a reader should confirm with the team.

    Elements marked `"assumption": true`, and — because the safe default is
    that anything unproven is an assumption — elements that carry neither
    evidence nor a marking. That second group catches the `"assumptions"`
    typo, which otherwise drops the element out of this list silently.
    """
    items = []
    unmarked = not model.get("_facts_only")
    for section in ("people", "containers", "external_systems"):
        for element in model.get(section) or []:
            description = element.get("description") or "no description"
            if element.get("assumption"):
                items.append(f"- **{element['name']}**: {description}")
            elif unmarked and not element.get("evidence"):
                items.append(f"- **{element['name']}** (unmarked, no evidence): {description}")
    for r in model.get("relationships") or []:
        if r.get("assumption"):
            items.append(f"- **{r['from']} → {r['to']}**: {r.get('description', '')}")
    for flow in model.get("flows") or []:
        steps = flow.get("steps") or []
        if flow.get("assumption"):
            items.append(f"- **{flow['name']}** (key flow): {flow.get('description') or 'no description'}")
            continue
        for number, step in enumerate(steps, 1):
            if _unproven(flow, step):
                items.append(
                    f"- **{flow['name']}**, step {number} ({step.get('from')} → {step.get('to')}): "
                    f"{step.get('description') or 'no description'}"
                )
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


def _deployment_section(facts, model, svg_ok, mermaid, svg_error=None):
    deployment = facts.get("deployment") or {}
    if not any(deployment.get(k) for k in ("compose", "dockerfiles", "kubernetes", "ci", "platforms")):
        return []
    lines = ["### Deployment", ""]
    if mermaid:
        lines.append(_section("#### docker compose", "c4-deployment", mermaid, svg_ok, svg_error=svg_error))
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


def _summary_section(model):
    """The agent's overview, findings and recommendations from c4-model.json `summary`."""
    summary = model.get("summary") or {}
    if model.get("_facts_only") or not summary:
        return []
    lines = ["## Architecture overview", ""]
    if summary.get("overview"):
        lines += [summary["overview"].strip(), ""]
    for key, title in (("findings", "Findings"), ("recommendations", "Recommendations")):
        items = [item.strip() for item in summary.get(key) or [] if item.strip()]
        if items:
            lines += [f"### {title}", ""] + [f"- {item}" for item in items] + [""]
    return lines


def _unreviewed_facts_section(facts, drift):
    """The `### Unreviewed facts` subsection: facts the model doesn't cover yet."""
    if not drift:
        return []
    by_id = {}
    for kind in ("containers", "data_stores", "external_systems"):
        for fact in facts[kind]:
            by_id[fact["id"]] = ({"containers": "container", "data_stores": "data store",
                                  "external_systems": "external system"}[kind], fact)
    rows = ["| id | name | kind | evidence |", "|---|---|---|---|"]
    for message in drift:
        first_token = message.split(" ", 1)[0]
        kind, fact = by_id.get(first_token, ("?", None))
        if fact is None:
            rows.append(f"| `{first_token}` | | {kind} | |")
            continue
        evidence = ", ".join(f"`{e}`" for e in (fact.get("evidence") or [])[:4])
        rows.append(f"| `{fact['id']}` | {_cell(fact.get('name', ''))} | {kind} | {evidence or '—'} |")
    return ["### Unreviewed facts", "",
            "Facts discovered in the code since this model was written. Add each to the model (or list it in `excluded` with a reason) before the next render.",
            ""] + rows + [""]


def _repository(facts, output, repo_override=None):
    """
    The analysed repository, or None when it can't be found from here (the
    output folder moved and no --repo was given): evidence isn't checked then.
    """
    relative = repo_override or facts.get("repository_root")
    if not relative:
        return None
    repo = (Path(output) / relative).resolve()
    expected = facts.get("repository")
    if not repo.is_dir() or (not repo_override and expected and repo.name != expected):
        return None
    return repo


def render(output_dir, facts_only=False, svg=True, repo_override=None, collector=None):
    """Render C4 diagrams tiered by status.

    Returns a dict with `status`, `errors`, `drift`, `warnings`, `diagrams`,
    `facts_only`, `svg` and `svg_failed`. `status` is one of `ok`, `drift`,
    `invalid`. When the model is invalid the facts-only model is drawn; the
    errors are preserved. When the model drifts the model is rendered as-is
    and an `Unreviewed facts` section is appended to the C4 block.
    """
    output = Path(output_dir).resolve()
    facts_file = output / "c4-facts.json"
    if not facts_file.is_file():
        raise UserError(
            f"{facts_file} not found; run analyze_repository.py first"
        )
    facts = json.loads(facts_file.read_text(encoding="utf-8"))
    for key in REQUIRED_FACTS:
        if key not in facts:
            raise UserError(
                f"{key} missing; re-run analyze_repository.py", path="c4-facts.json"
            )
    model_file = output / "c4-model.json"

    result = ValidationResult(model=None)
    use_model = None
    code_entries = []
    if facts_only or not model_file.is_file():
        use_model = facts_only_model(facts)
    else:
        loaded = load_model(model_file)
        result = loaded
        if loaded.errors:
            # JSON syntax error or non-object top level: fall back to facts-only.
            use_model = facts_only_model(facts)
            for err in loaded.errors:
                if collector:
                    collector.model_error("render_c4", err)
        else:
            model = loaded.model
            for key in ("people", "containers", "external_systems", "relationships", "excluded", "flows"):
                model.setdefault(key, [])
            structural = check_structure(model)
            result.errors.extend(structural.errors)
            if result.errors:
                use_model = facts_only_model(facts)
                for err in structural.errors:
                    if collector:
                        collector.model_error("render_c4", err)
            else:
                # Semantic checks: append to the existing ValidationResult.
                result = validate(model, facts, result, repo=_repository(facts, output, repo_override))
                if result.errors:
                    use_model = facts_only_model(facts)
                    for err in result.errors:
                        if collector:
                            collector.model_error("render_c4", err)
                else:
                    use_model = model

    # code_diagrams.prepare is only run when we have a usable model.
    if not use_model.get("_facts_only") and not result.errors:
        code_errors, code_warnings, code_entries = code_diagrams.prepare(
            use_model, facts, output, collector, repo_override=repo_override
        )
        result.warnings.extend(code_warnings)
        if code_errors:
            # Map code_diagrams errors into the invalid tier; fall back to facts-only.
            result.errors.extend(code_errors)
            use_model = facts_only_model(facts)
            for err in code_errors:
                if collector:
                    collector.model_error("render_c4", err)

    status = result.status
    if collector and status == "drift":
        for message in result.drift:
            collector.model_warning("render_c4", message)

    for old in list(output.glob("c4-*.mmd")) + list(output.glob("c4-*.svg")):
        old.unlink()

    diagrams = {}
    if not use_model.get("_facts_only"):
        diagrams["c4-context"] = context_diagram(use_model)
    if use_model["containers"]:
        diagrams["c4-container"] = container_diagram(use_model)
    components = component_diagrams(use_model, facts)
    for stem, _, mermaid, _, _ in components:
        diagrams[stem] = mermaid
    flows = flow_diagrams(use_model, facts)
    for stem, _, mermaid, _ in flows:
        diagrams[stem] = mermaid
    for entry in code_entries:
        entry["mermaid"] = _with_title(entry["mermaid"], entry["title"])
        diagrams[entry["stem"]] = entry["mermaid"]
    deployment = deployment_diagram(facts, use_model)
    if deployment:
        diagrams["c4-deployment"] = deployment

    for stem, mermaid in diagrams.items():
        (output / f"{stem}.mmd").write_text(mermaid, encoding="utf-8")

    env_disabled = _sr.disabled_by_env()

    rendered: dict = {}
    render_results: list = []
    # Stems whose image failed for a reason the user can act on. A machine
    # with no mermaid-cli is not one of them: that is one note for the whole
    # run, not a note under every diagram.
    svg_errors: dict = {}
    if svg and not env_disabled:
        stems = [(stem, output / f"{stem}.mmd") for stem in diagrams]
        render_results = _sr.render(stems, output)
        for r in render_results:
            rendered[r.stem] = r.status == "ok"
            if r.status not in ("ok", "missing-tool", "skipped"):
                svg_errors[r.stem] = (r.status, r.message)

    block = [BLOCK_START, ""] + _summary_section(use_model) + ["## Architecture (C4 model)", ""]
    if use_model.get("_facts_only"):
        block += [
            "> Drawn from code facts only: no `c4-model.json` yet, so people, external purposes, "
            "descriptions and key flows are missing and the System Context level is left out. "
            "Write `c4-model.json` and run `render_c4.py` to complete it.", "",
        ]
    if not use_model["containers"]:
        block += ["> No containers, data stores or external systems were detected, so there are no C4 diagrams. "
                  "Build the model from the source by hand, or see the dependency graph appendix.", ""]
    elif use_model["system"].get("description") and not use_model.get("_facts_only"):
        block += [_prose(use_model["system"]["description"]), ""]

    block += _key_section(diagrams.values())

    if "c4-context" in diagrams:
        block.append(_section("### Level 1: System context", "c4-context", diagrams["c4-context"],
                              rendered.get("c4-context"), svg_error=svg_errors.get("c4-context")))
    if "c4-container" in diagrams:
        block.append(_section("### Level 2: Containers", "c4-container", diagrams["c4-container"],
                              rendered.get("c4-container"), svg_error=svg_errors.get("c4-container")))
        block += _containers_table(use_model, facts) + [""]

    if components:
        block += ["### Level 3: Components", "",
                  "For each container: the modules it is built from (when it has several), then the code structure "
                  "inside them (packages or namespaces and the imports between them).", ""]
        for stem, title, mermaid, notes, _kind in components:
            block.append(_section(f"#### {title}", stem, mermaid, rendered.get(stem), notes,
                                  svg_error=svg_errors.get(stem)))

    if code_entries:
        block += ["### Level 4: Code", "",
                  "The classes and interfaces of the key components: inheritance, implemented interfaces, "
                  "dependencies inside the component and public methods. Boxes marked external live in another component.", ""]
        for entry in code_entries:
            block.append(_section(f"#### {_prose(entry['title'])}", entry["stem"], entry["mermaid"],
                                  rendered.get(entry["stem"]), code_diagrams.notes(entry), intro=entry["description"],
                                  svg_error=svg_errors.get(entry["stem"])))

    if flows:
        block += ["### Key flows", "", "How a request moves through the system, step by step.", ""]
        for stem, title, mermaid, description in flows:
            block.append(_section(f"#### {_prose(title)}", stem, mermaid, rendered.get(stem), intro=description,
                                  svg_error=svg_errors.get(stem)))

    block += _deployment_section(facts, use_model, rendered.get("c4-deployment"), deployment,
                                 svg_error=svg_errors.get("c4-deployment"))
    block += _endpoints_section(facts, use_model)
    block += _configuration_section(facts, use_model)
    block += _inventory_section(facts, use_model)

    assumptions = _assumptions(use_model)
    if assumptions:
        block += ["### Assumptions", "", "Not backed by code evidence; confirm with the team:", ""] + assumptions + [""]

    # On drift, list the facts the model doesn't cover yet.
    block += _unreviewed_facts_section(facts, result.drift)

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
            text = pattern.sub(lambda _: "\n".join(block), text)
        else:
            result.warnings.append("ArchitectureReport.md has no C4 block; re-run analyze_repository.py")
        if not use_model.get("_facts_only"):
            # The analyzer writes the report before the model is read, so its
            # Executive Summary can only count projects. Now that the model is
            # loaded and valid, say what the system is made of instead.
            text = generate_docs.replace_summary(text, generate_docs.model_summary(use_model))
            # Same reason as the summary: the analyzer could only describe the
            # package graph, where a leaf package reads as a strength.
            text = generate_docs.replace_strengths(
                text,
                generate_docs.model_strengths(
                    use_model,
                    _coverage(use_model, facts, result),
                    generate_docs.graph_strengths(text),
                ),
            )
        report.write_text(text, encoding="utf-8")

    # Per-diagram SVG status for summary.json.
    svg_status = {}
    for r in render_results:
        svg_status[r.stem] = {"status": r.status, "message": r.message}

    return {
        "status": status,
        "errors": result.errors,
        "drift": result.drift,
        "warnings": result.warnings,
        "diagrams": list(diagrams),
        "svg_failed": [stem for stem, ok in rendered.items() if not ok] if svg else [],
        "facts_only": bool(use_model.get("_facts_only")),
        "svg": svg_status,
        "coverage": _coverage(use_model, facts, result),
    }


def main():
    parser = argparse.ArgumentParser(description="Draw the C4 diagrams from c4-facts.json and c4-model.json.")
    parser.add_argument("output", help="Output folder written by analyze_repository.py")
    parser.add_argument("--facts-only", action="store_true", help="Ignore c4-model.json and draw from the facts alone")
    parser.add_argument("--no-svg", action="store_true", help="Skip SVG rendering")
    parser.add_argument("--repo", dest="repo", default=None,
                        help="Override the repository path stored in c4-facts.json (for relocatable output)")
    parser.add_argument("--debug", action="store_true", help="Print the full traceback when an unexpected error occurs")
    parser.add_argument("--strict", action="store_true",
                        help="Exit with code 2 when the model drifts from the code (the DRIFT: lines)")
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
    for message in result["drift"]:
        print(f"DRIFT: {message}")
    coverage = result["coverage"]
    print(COVERAGE_LINE.format(
        *coverage["facts"], *coverage["containers_described"],
        *coverage["components_described"],
        coverage["people"], coverage["flows"], coverage["code"]))
    svg_status = result.get("svg", {})
    missing_tool = False
    for stem in result["svg_failed"]:
        info = svg_status.get(stem, {})
        status = info.get("status", "unknown")
        if status == "missing-tool":
            missing_tool = True
            continue
        msg = info.get("message", "")
        print(f"WARNING: {stem}: {status}" + (f" — {msg}" if msg else ""))
    if missing_tool:
        print("NOTE: SVGs not rendered: neither mmdc nor npx is on PATH. "
              "The report shows the Mermaid source instead.")
    # Exit codes: 0 ok, 0 drift (DRIFT: lines printed), 1 invalid, 2 drift with --strict.
    if result["status"] == "drift" and args.strict:
        sys.exit(2)


if __name__ == "__main__":
    # --debug is read from argv here: run_cli needs it before main() parses.
    run_cli(main, debug="--debug" in sys.argv)
