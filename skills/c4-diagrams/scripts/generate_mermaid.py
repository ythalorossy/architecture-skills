"""
dependency-graph.mmd: the project graph as a Mermaid flowchart.

The one diagram the analyzer draws itself; every other .mmd comes from
render_c4.py. Nodes are projects, edges are references, and groups become
subgraphs. Ids are allocated through mermaid_syntax so a project name can hold
any character without breaking the diagram.
"""
from pathlib import Path

from scripts import mermaid_syntax as _ms


def _node_ids(names, alloc=None):
    """Mermaid ids are plain identifiers; the real names go in the labels."""
    alloc = alloc or _ms.IdAllocator("flowchart")
    return {name: alloc.id(name) for name in names}


def _label(text):
    """Escape text for a flowchart label string (``["label"]``)."""
    # Plain, not markdown: mermaid parses no Markdown in ["label"], so a
    # markdown escape would reach the diagram as a literal backslash.
    return _ms.label_text("flowchart_plain", text)


def generate_mermaid(graph, groups=None, title=None):
    """
    Render the dependency graph as a Mermaid flowchart.

    groups optionally maps a project name to a folder (e.g. src/Domain);
    projects sharing a folder are drawn inside one subgraph. Targets that are
    not keys of the graph (unresolved references) get a dashed border. title
    is written as front matter, so the file says what it is on its own.
    """
    groups = groups or {}

    external = sorted({
        target
        for targets in graph.values()
        for target in targets
        if target not in graph
    })

    alloc = _ms.IdAllocator("flowchart")
    ids = _node_ids(list(graph) + external, alloc)

    by_group = {}

    for name in graph:
        by_group.setdefault(groups.get(name, ""), []).append(name)

    group_ids = {
        f"group_{group}": alloc.internal(f"group_{group}")
        for group in by_group
        if group
    }

    lines = [
        "graph TD"
    ]

    for group, names in sorted(by_group.items()):
        indent = "    "

        if group:
            lines.append(
                f'    subgraph {group_ids[f"group_{group}"]}["{_label(group)}"]'
            )
            indent = "        "

        for name in names:
            lines.append(f'{indent}{ids[name]}["{_label(name)}"]')

        if group:
            lines.append("    end")

    for name in external:
        lines.append(f'    {ids[name]}["{_label(name)}"]')

    for source, targets in graph.items():
        for target in targets:
            lines.append(
                f"    {ids[source]} --> {ids[target]}"
            )

    if external:
        lines.append("    classDef external stroke-dasharray: 5 5")
        lines.append(
            "    class "
            + ",".join(ids[name] for name in external)
            + " external"
        )

    mermaid = "\n".join(lines) + "\n"
    return _ms.with_title(mermaid, title) if title else mermaid


def save_mermaid(graph, output_file, groups=None, title=None):
    content = generate_mermaid(graph, groups, title)

    Path(output_file).write_text(
        content,
        encoding="utf-8"
    )


if __name__ == "__main__":
    import json
    import sys

    with open(sys.argv[1], encoding="utf-8") as file:
        graph = json.load(file)

    save_mermaid(
        graph,
        sys.argv[2] if len(sys.argv) > 2 else "dependency-graph.mmd"
    )
