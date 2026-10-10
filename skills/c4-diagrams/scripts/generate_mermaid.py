from pathlib import Path
import re

from scripts import mermaid_syntax as _ms


def _node_ids(names):
    """Mermaid IDs must be plain identifiers; delegates to mermaid_syntax (SPEC-04)."""
    alloc = _ms.IdAllocator("flowchart")
    return {name: alloc.id(name) for name in names}


def _label(text):
    """Escape text for a flowchart label string (``["label"]``); delegates to mermaid_syntax (SPEC-04)."""
    return _ms.label_text("flowchart_md", text)


def generate_mermaid(graph, groups=None):
    """
    Render the dependency graph as a Mermaid flowchart.

    groups optionally maps a project name to a folder (e.g. src/Domain);
    projects sharing a folder are drawn inside one subgraph. Targets that are
    not keys of the graph (unresolved references) get a dashed border.
    """
    groups = groups or {}

    external = sorted({
        target
        for targets in graph.values()
        for target in targets
        if target not in graph
    })

    ids = _node_ids(list(graph) + external)

    by_group = {}

    for name in graph:
        by_group.setdefault(groups.get(name, ""), []).append(name)

    group_ids = _node_ids([
        f"group_{group}"
        for group in by_group
        if group
    ])

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

    return "\n".join(lines) + "\n"


def render_svg(mermaid_file, svg_file, timeout=180):
    """
    Render a .mmd file to SVG with mermaid-cli, so the report can show the
    diagram as an image in viewers that don't render Mermaid (e.g. VS Code's
    built-in preview). Uses `mmdc` if installed, else `npx`. Returns True on
    success; any failure (no Node, no network, timeout) returns False.
    """
    import shutil
    import subprocess

    # Use the full path from shutil.which(): on Windows these are .cmd shims
    # (npx.cmd, mmdc.cmd) that subprocess can't start by bare name.
    mmdc = shutil.which("mmdc")
    npx = shutil.which("npx")
    if mmdc:
        command = [mmdc]
    elif npx:
        command = [npx, "-y", "@mermaid-js/mermaid-cli"]
    else:
        return False

    import json
    import tempfile

    # Plain <text> labels: HTML labels (<foreignObject>) go blank in some
    # viewers when the SVG is shown as an <img>.
    config = {
        "htmlLabels": False,
        "markdownAutoWrap": False,
        "flowchart": {"htmlLabels": False, "wrappingWidth": 1000}
    }

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as file:
        json.dump(config, file)
        config_file = file.name

    try:
        result = subprocess.run(
            command + [
                "-i", str(mermaid_file),
                "-o", str(svg_file),
                "-c", config_file,
                "-b", "white"
            ],
            capture_output=True,
            timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        Path(config_file).unlink(missing_ok=True)

    return result.returncode == 0 and Path(svg_file).is_file()


def save_mermaid(graph, output_file, groups=None):
    content = generate_mermaid(graph, groups)

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
