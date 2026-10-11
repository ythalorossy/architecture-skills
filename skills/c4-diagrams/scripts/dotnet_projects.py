import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath


try:
    from scripts.repo_index import is_ignored_dir, IGNORED_DIRS, RepoIndex
    from scripts.paths import normalize_include, resolve_include, local_tag, project_group
except ImportError:
    from repo_index import is_ignored_dir, IGNORED_DIRS, RepoIndex
    from paths import normalize_include, resolve_include, local_tag, project_group


PROJECT_EXTENSIONS = (".csproj", ".fsproj", ".vbproj")

SLN_PROJECT_LINE = re.compile(
    r'^Project\("\{[^}]+\}"\)\s*=\s*"([^"]+)",\s*"([^"]+)"',
    re.MULTILINE
)


def solution_project_paths(solution_file, collector=None):
    """Return the absolute project paths listed in a .sln or .slnx file."""
    paths = set()

    if solution_file.suffix == ".slnx":
        try:
            root = ET.parse(solution_file).getroot()
        except ET.ParseError as ex:
            if collector:
                collector.parse_error("dotnet_projects", str(solution_file), f"invalid XML: {ex}")
            return paths

        for element in root.iter():
            if local_tag(element) == "Project" and element.attrib.get("Path"):
                paths.add(resolve_include(solution_file.parent, element.attrib["Path"]))
        return paths

    text = solution_file.read_text(encoding="utf-8-sig", errors="replace")
    for _, include in SLN_PROJECT_LINE.findall(text):
        if include.endswith(PROJECT_EXTENSIONS):
            paths.add(resolve_include(solution_file.parent, include))
    return paths


def project_references(project_file, collector=None):
    """Return the resolved paths of <ProjectReference> items in a project file."""
    try:
        root = ET.parse(project_file).getroot()
    except ET.ParseError as ex:
        if collector:
            collector.parse_error("dotnet_projects", str(project_file), f"invalid XML: {ex}")
        return []

    references = []
    for element in root.iter():
        if local_tag(element) != "ProjectReference":
            continue
        include = element.attrib.get("Include")
        if include:
            references.append(resolve_include(project_file.parent, include))
    return references


def discover_projects(repo_path, index=None, collector=None):
    """
    Find every .NET project and work out a unique display name for each.

    When the repository has solution files, projects not listed in any of them
    are flagged with in_solution=False (stray or abandoned project files).

    The `index` parameter is accepted for API compatibility but not yet used
    (the .NET module has minimal I/O compared to other ecosystems).
    Pass a DiagnosticsCollector to route warnings through the diagnostics channel.
    """
    repo = Path(repo_path).resolve()

    index = RepoIndex.ensure(index, repo, collector)
    solution_files = list(index.walk(lambda name: name.endswith((".sln", ".slnx"))))
    project_files = list(index.walk(lambda name: name.endswith(PROJECT_EXTENSIONS)))

    solutions = solution_files
    solution_paths = set()
    for solution in solutions:
        solution_paths |= solution_project_paths(solution, collector)

    projects = []
    for project_file in project_files:
        project_file = project_file.resolve()
        relative = project_file.relative_to(repo).as_posix()
        projects.append({
            "name": project_file.stem,
            "path": project_file,
            "relative_path": relative,
            "group": project_group(relative),
            "in_solution": (project_file in solution_paths) if solutions else None,
        })

    assign_unique_names(projects)

    return {
        "solutions": [s.relative_to(repo).as_posix() for s in solutions],
        "projects": projects,
    }


def assign_unique_names(projects):
    by_name = {}
    for project in projects:
        by_name.setdefault(project["name"], []).append(project)

    for name, same_name in by_name.items():
        if len(same_name) == 1:
            same_name[0]["id"] = name
            same_name[0]["duplicate_name"] = False
            continue

        # Solution projects keep the plain name; others get their path appended.
        in_solution = [p for p in same_name if p["in_solution"]]
        keep_plain = in_solution[0] if len(in_solution) == 1 else None

        for project in same_name:
            project["duplicate_name"] = True
            project["id"] = (
                name if project is keep_plain
                else f"{name} ({project['relative_path']})"
            )
