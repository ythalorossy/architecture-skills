from pathlib import Path, PurePosixPath


def build_dependency_graph(repo_path, include_orphans=False, index=None, discovery=None):
    """
    Map each project name to the names of the projects it references.

    Covers .NET, Node.js, Python and Java projects (see projects.py). Projects
    outside every solution/workspace/aggregator are left out unless
    include_orphans is set. A reference to a project that cannot be found keeps
    its name (or file stem), so it shows up as a target that is not itself a
    key in the graph.
    """
    if discovery is None:
        from scripts.projects import discover_all
        discovery = discover_all(repo_path, index)
    projects = [
        project
        for project in discovery["projects"]
        if include_orphans or project["in_solution"] is not False
    ]

    ids_by_path = {
        project["path"]: project["id"]
        for project in projects
    }

    graph = {}

    for project in projects:
        dependencies = []

        for reference in project["references"]:
            dependency = (
                reference if isinstance(reference, str)
                else ids_by_path.get(reference, PurePosixPath(reference.as_posix()).stem)
            )

            if dependency not in dependencies:
                dependencies.append(dependency)

        graph[project["id"]] = sorted(dependencies)

    return dict(sorted(graph.items()))


def build_groups(repo_path, include_orphans=False, index=None, discovery=None):
    """Map each project name to its folder group (e.g. src/Domain), used for diagram subgraphs."""
    if discovery is None:
        from scripts.projects import discover_all
        discovery = discover_all(repo_path, index)
    return {
        project["id"]: project["group"]
        for project in discovery["projects"]
        if include_orphans or project["in_solution"] is not False
    }


if __name__ == "__main__":
    import json
    import sys

    graph = build_dependency_graph(sys.argv[1])

    print(json.dumps(graph, indent=2))
