from pathlib import Path
import re


GENERATOR_VERSION = "3.3.7"


def _generated_date():
    """Wall-clock timestamp; only called when --timestamp is passed."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _report_metadata(generated_on):
    """Report metadata block: version always, Generated On only when timestamped."""
    parts = [f"Generator Version: {GENERATOR_VERSION}"]
    if generated_on:
        parts.insert(0, f"Generated On: {generated_on}")
    lines = "\n".join(parts)
    return "---\n\n## Report Metadata\n\n" + lines + "\n"

ASSETS_DIR = (
    Path(__file__).parent.parent / "assets"
)

# The Executive Summary's first paragraph is written twice: once here, from
# the dependency graph, and again by render_c4 once c4-model.json has been
# read and validated. Markdown "comments" (empty link definitions) mark the
# part that may be replaced, the same way the C4 block is marked.
SUMMARY_START = "[//]: # (summary:start)"
SUMMARY_END = "[//]: # (summary:end)"

# The Strengths list is written twice for the same reason, from the graph
# here and from the model once it has been read.
STRENGTHS_START = "[//]: # (strengths:start)"
STRENGTHS_END = "[//]: # (strengths:end)"

TEST_PROJECT = re.compile(
    r"(^|[.\-_])(Unit|Integration|Functional|Acceptance|E2E)?(Tests?|Specs?)$",
    re.IGNORECASE
)


def load_template(template_name):
    template_path = (
        ASSETS_DIR / template_name
    )

    return template_path.read_text(
        encoding="utf-8"
    )


def is_test_project(name):
    return bool(TEST_PROJECT.search(name))


def _count(number, singular, plural=None):
    return f"{number} {singular if number == 1 else (plural or singular + 's')}"


def _listed(parts):
    """'a', 'a and b', 'a, b and c'."""
    if len(parts) < 2:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def model_summary(model):
    """The Executive Summary paragraphs for a repository that has a model.

    The dependency graph counts projects, which are not the parts of a running
    system: a Python package is not a container. When `c4-model.json` says what
    the system is made of, that answer opens the report instead of the count.
    """
    system = model.get("system") or {}
    name = str(system.get("name") or "").strip() or "The system"
    description = str(system.get("description") or "").strip()

    containers = model.get("containers") or []
    stores = [e for e in containers if e.get("type") in ("database", "queue")]
    counts = [_count(len(containers) - len(stores), "container")]
    for items, singular, plural in (
        (stores, "data store", None),
        (model.get("external_systems") or [], "external system", None),
        (model.get("people") or [], "person", "people"),
        (model.get("relationships") or [], "relationship", None),
        (model.get("flows") or [], "key flow", None),
    ):
        if items:
            counts.append(_count(len(items), singular, plural))

    paragraphs = []
    if description:
        paragraphs.append(description if description.endswith((".", "!", "?")) else description + ".")
    paragraphs.append(f"The model of {name} describes {_listed(counts)}.")
    return "\n\n".join(paragraphs)


def model_strengths(model, coverage, graph_strengths=()):
    """What a reader can rely on in a repository that has a model.

    The graph-derived list answers "which packages depend on nothing?",
    which is a fact about packaging, not a strength of the architecture: a
    leaf package is not a good sign or a bad one. With a model, a strength
    is something the model proves — every container explained, every
    element backed by code, the flows written down. Each line is checked,
    so the section stays empty rather than flattering a thin model.
    """
    strengths = []

    covered, total = coverage.get("facts") or [0, 0]
    if total and covered == total:
        strengths.append("Every container, data store and external system found in the code is in the model.")

    described, containers = coverage.get("containers_described") or [0, 0]
    if containers and described == containers:
        strengths.append("Every container says what it is responsible for.")

    described, components = coverage.get("components_described") or [0, 0]
    if components and described == components:
        strengths.append("Every component says what it does.")

    people = model.get("people") or []
    if people:
        names = [str(p.get("name") or p.get("id") or "").strip() for p in people]
        strengths.append("The model names who the system is for: " + _listed([n for n in names if n]) + ".")

    flows = model.get("flows") or []
    if flows:
        titles = [str(f.get("name") or f.get("title") or f.get("id") or "").strip() for f in flows]
        named = _listed([t for t in titles if t])
        verb = "is" if len(flows) == 1 else "are"
        strengths.append(f"{_count(len(flows), 'key flow')} {verb} written down end to end: {named}.")

    if not _unproven(model):
        strengths.append("Every container and external system points at the code that proves it.")

    return strengths + [s for s in graph_strengths if s.startswith("No circular")]


def _unproven(model):
    """Containers or systems a reader would have to take on trust.

    People are left out: a role is a judgement about the world, not
    something a repository can prove, and every model would lose the line.
    """
    for section in ("containers", "external_systems"):
        for element in model.get(section) or []:
            if element.get("assumption") or not element.get("evidence"):
                return True
    return False


def graph_strengths(text):
    """The strengths already in the report, so the dependency-graph checks survive a rewrite."""
    marked = re.compile(re.escape(STRENGTHS_START) + "(.*?)" + re.escape(STRENGTHS_END), re.DOTALL)
    found = marked.search(text)
    if not found:
        return []
    return [line.lstrip("- ").strip() for line in found.group(1).splitlines() if line.startswith("- ")]


def replace_strengths(text, strengths):
    """Swap the marked Strengths list in `text`. Unmarked text is left alone."""
    marked = re.compile(re.escape(STRENGTHS_START) + ".*?" + re.escape(STRENGTHS_END), re.DOTALL)
    if not marked.search(text):
        return text
    body = "\n".join(f"- {line}" for line in strengths) if strengths else (
        "The model does not show one yet; see the Coverage line under Architecture (C4 model)."
    )
    block = "\n\n".join([STRENGTHS_START, body, STRENGTHS_END])
    return marked.sub(lambda _: block, text)


def replace_summary(text, paragraph):
    """Swap the marked Executive Summary paragraph in `text` for `paragraph`.

    Returns the text unchanged when the markers are missing: an older report,
    or one the user rewrote by hand, is left alone rather than guessed at.
    """
    marked = re.compile(re.escape(SUMMARY_START) + ".*?" + re.escape(SUMMARY_END), re.DOTALL)
    if not marked.search(text):
        return text
    block = "\n\n".join([SUMMARY_START, paragraph, SUMMARY_END])
    return marked.sub(lambda _: block, text)


def find_cycles(graph):
    """Return each dependency cycle once, as a list of project names."""
    cycles = []
    seen = set()
    state = {}
    stack = []

    def visit(node):
        state[node] = "visiting"
        stack.append(node)

        for target in graph.get(node, []):
            if target not in graph:
                continue

            if state.get(target) == "visiting":
                cycle = stack[stack.index(target):]
                key = frozenset(cycle)

                if key not in seen:
                    seen.add(key)
                    cycles.append(cycle + [target])

            elif target not in state:
                visit(target)

        stack.pop()
        state[node] = "done"

    for node in graph:
        if node not in state:
            visit(node)

    return cycles


def analyze_graph(graph, scan=None):
    """Derive facts about the graph that the report and the summary both use."""
    scan = scan or {}

    used_by = {name: [] for name in graph}
    unresolved = []

    for source, targets in graph.items():
        for target in targets:
            if target in used_by:
                used_by[target].append(source)
            else:
                unresolved.append((source, target))

    tests = sorted(name for name in graph if is_test_project(name))
    production = sorted(name for name in graph if name not in tests)

    tested = {
        target
        for test in tests
        for target in graph[test]
    }

    return {
        "used_by": used_by,
        "tests": tests,
        "production": production,
        "core": [name for name in production if not graph[name]],
        "untested": [name for name in production if name not in tested] if tests else [],
        "multi_target_tests": [
            test for test in tests
            if len([t for t in graph[test] if t in production]) > 1
        ],
        "cycles": find_cycles(graph),
        "unresolved": unresolved,
        "orphans": scan.get("orphan_projects", []),
        "duplicates": scan.get("duplicate_project_names", []),
        "solutions": scan.get("solutions", [])
    }


def _bullets(items, empty):
    return "\n".join(f"- {item}" for item in items) if items else empty


def _components_table(graph, facts, groups, ecosystems):
    rows = [
        "| Project | Ecosystem | Folder | Kind | Depends on | Used by |",
        "|---|---|---|---|---|---|"
    ]

    for name in graph:
        kind = "test" if name in facts["tests"] else "production"
        rows.append(
            f"| {name} | {ecosystems.get(name, '-')} | {groups.get(name) or '-'} | {kind} "
            f"| {len(graph[name])} | {len(facts['used_by'][name])} |"
        )

    return "\n".join(rows)


def _dependency_sections(graph, facts):
    sections = []

    for source, targets in graph.items():
        sections.append(f"### {source}")

        if targets:
            for target in targets:
                note = "" if target in graph else " (unresolved)"
                sections.append(f"- depends on {target}{note}")
        else:
            sections.append("- no project references")

        users = facts["used_by"][source]
        if users:
            sections.append(f"- used by {', '.join(users)}")

        sections.append("")

    return "\n".join(sections).rstrip()


def _strengths(facts, graph):
    strengths = []

    if graph and not facts["cycles"]:
        strengths.append("No circular project references.")

    if facts["core"]:
        strengths.append(
            "Projects with no project references (the core that the rest builds on): "
            + ", ".join(facts["core"]) + "."
        )

    if facts["solutions"] and not facts["orphans"]:
        strengths.append("Every project is listed in a solution, workspace or aggregator build.")

    if facts["tests"] and not facts["untested"]:
        strengths.append("Every production project is referenced by a test project.")

    return strengths


def _concerns_and_recommendations(facts):
    concerns = []
    recommendations = []

    for cycle in facts["cycles"]:
        concerns.append("Circular reference: " + " -> ".join(cycle) + ".")
    if facts["cycles"]:
        recommendations.append(
            "Break the circular references, for example by moving the shared "
            "contracts into a project both sides can depend on."
        )

    if facts["orphans"]:
        concerns.append(
            "Projects not listed in any solution, workspace or aggregator POM: "
            + ", ".join(facts["orphans"]) + "."
        )
        recommendations.append(
            "Check whether the stray projects are still used: add them to the "
            "solution/workspace/aggregator, delete them, or leave them if they are "
            "intentionally standalone (examples, fixtures)."
        )

    if facts["duplicates"]:
        concerns.append(
            "More than one project file uses the name: "
            + ", ".join(facts["duplicates"]) + "."
        )
        recommendations.append("Give every project a unique name.")

    if facts["unresolved"]:
        concerns.append(
            "References to projects that were not found: "
            + ", ".join(f"{s} -> {t}" for s, t in facts["unresolved"]) + "."
        )
        recommendations.append("Fix or remove the broken project references.")

    if facts["untested"]:
        concerns.append(
            "Production projects that no test project references: "
            + ", ".join(facts["untested"]) + "."
        )
        recommendations.append("Add test projects for the untested production projects.")

    if facts["multi_target_tests"]:
        concerns.append(
            "Test projects that reference more than one production project "
            "(check whether unit and integration tests are mixed): "
            + ", ".join(facts["multi_target_tests"]) + "."
        )
        recommendations.append(
            "Keep each test project focused on one layer, and move cross-layer tests "
            "to a dedicated integration test project."
        )

    return concerns, recommendations


def generate_report(
    project_name,
    stacks,
    graph,
    scan=None,
    groups=None,
    mermaid=None,
    diagram_image=None,
    timestamp=False,
):
    generated_on = _generated_date() if timestamp else ""
    template = load_template(
        "architecture-report-template.md"
    )

    groups = groups or {}
    facts = analyze_graph(graph, scan)
    ecosystems = {
        project["name"]: project["ecosystem"]
        for project in (scan or {}).get("projects", [])
    }

    strengths = _strengths(facts, graph)
    concerns, recommendations = _concerns_and_recommendations(facts)

    internal_edges = sum(
        1
        for targets in graph.values()
        for target in targets
        if target in graph
    )

    folders = sorted({group for group in groups.values() if group})

    if graph:
        # Replaced by render_c4 when c4-model.json describes the system.
        described = (
            f"{project_name} has {len(graph)} projects "
            f"({len(facts['production'])} production, {len(facts['tests'])} test) "
            f"with {internal_edges} project references between them."
        )
        checks = (
            f"The automated dependency checks found {len(concerns)} concern(s)."
            if concerns
            else "The automated dependency checks found no structural concerns."
        )
    else:
        # An empty graph is "not analyzed", not "healthy".
        described = (
            f"No supported projects were found in {project_name} (.NET projects, "
            "package.json packages, Python packages, Maven or Gradle modules), so "
            "this report says nothing about its structure. Analyze it directly."
        )
        checks = ""

    executive_summary = "\n\n".join(
        [SUMMARY_START, described, SUMMARY_END] + ([checks] if checks else [])
    )

    overview = [
        f"**Solutions / build roots:** {', '.join(facts['solutions']) or 'none found'}",
        "",
        f"**Project folders:** {', '.join(folders) or 'none'}"
    ]

    if mermaid and diagram_image:
        # The image shows in every Markdown viewer; the source stays for
        # viewers that render Mermaid (GitHub, GitLab) and for editing.
        overview += [
            "",
            "<details>",
            "<summary>Full dependency graph</summary>",
            "",
            f"![Dependency graph]({diagram_image})",
            "",
            "```mermaid", mermaid.rstrip(), "```",
            "",
            "</details>"
        ]
    elif mermaid:
        overview += ["", "<details>", "<summary>Full dependency graph</summary>", "",
                     "```mermaid", mermaid.rstrip(), "```", "", "</details>"]

    artifacts = [
        "- C4 diagrams: listed under Architecture (C4 model) above",
        "- [Mermaid source](dependency-graph.mmd)",
        "- [Dependency data (JSON)](dependency-graph.json)",
        "- [Repository scan (JSON)](repository-scan.json)",
        "- [Summary (JSON)](summary.json)"
    ]
    if diagram_image:
        artifacts.insert(0, f"- [Diagram image (SVG)]({diagram_image})")

    report = (
        template
        .replace("{{repository_name}}", project_name)
        .replace("{{technology_stack}}", _bullets(stacks, "- Unknown"))
        .replace("{{components}}", _components_table(graph, facts, groups, ecosystems))
        .replace("{{dependency_analysis}}", _dependency_sections(graph, facts))
        .replace("{{executive_summary}}", executive_summary)
        .replace("{{system_overview}}", "\n".join(overview))
        .replace("{{strengths}}", _bullets(strengths, "No notable strengths detected automatically."))
        .replace("{{concerns}}", _bullets(
            concerns,
            "No automated concerns detected." if graph
            else "Not analyzed: no supported projects found."
        ))
        .replace(
            "{{recommendations}}",
            _bullets(
                recommendations,
                "No changes recommended from the automated checks. "
                "Review the diagram for boundaries the checks cannot see."
                if graph else "Not analyzed: no supported projects found."
            )
        )
        .replace("{{artifacts}}", "\n".join(artifacts))
        .replace("{{report_metadata}}", _report_metadata(generated_on))
        .replace("{{generator_version}}", GENERATOR_VERSION)
    )

    return report
