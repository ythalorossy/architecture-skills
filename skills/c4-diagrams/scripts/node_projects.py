import json
import re
import sys
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

try:
    from scripts.repo_index import walk_files
    from scripts.paths import project_group
    from scripts.js_modules import module_projects
except ImportError:
    from repo_index import walk_files
    from paths import project_group
    from js_modules import module_projects


DEPENDENCY_FIELDS = (
    "dependencies", "devDependencies", "peerDependencies", "optionalDependencies"
)

# Version specs that only make sense for a package inside this repository.
LOCAL_SPEC = re.compile(r"^(workspace:|file:|link:|portal:)")


def _parse_json(path, collector=None):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as ex:
        if collector:
            collector.parse_error("node_projects", str(path), f"invalid JSON: {ex}")
        return None


def _pnpm_workspace_globs(file):
    """Read the `packages:` list of pnpm-workspace.yaml without a YAML parser."""
    globs = []
    in_packages = False

    for line in file.read_text(encoding="utf-8").splitlines():
        if re.match(r"^packages\s*:", line):
            in_packages = True
            continue
        if in_packages:
            item = re.match(r"^\s*-\s*['\"]?([^'\"#]+?)['\"]?\s*(#.*)?$", line)
            if item:
                globs.append(item.group(1))
            elif line.strip() and not line.startswith((" ", "\t")):
                break

    return globs


def _workspace_globs(directory, data):
    """Workspace patterns declared in a package.json or a sibling pnpm-workspace.yaml."""
    workspaces = data.get("workspaces")
    if isinstance(workspaces, dict):
        workspaces = workspaces.get("packages")

    globs = list(workspaces) if isinstance(workspaces, list) else []

    pnpm = directory / "pnpm-workspace.yaml"
    if pnpm.exists():
        globs += _pnpm_workspace_globs(pnpm)

    return globs


def _matches_workspace(relative_dir, root_dir, globs):
    included = False

    for glob in globs:
        negate = glob.startswith("!")
        pattern = PurePosixPath(root_dir, glob.lstrip("!").rstrip("/")).as_posix()
        pattern = pattern.removeprefix("./")
        if fnmatch(relative_dir, pattern) or fnmatch(relative_dir, pattern.replace("/**", "")):
            included = not negate

    return included


def discover_projects(repo_path, index=None, collector=None):
    """
    Find every package.json and link packages that depend on each other by name.

    When a workspace root exists (package.json "workspaces" or
    pnpm-workspace.yaml), the root itself is not drawn and packages outside
    every workspace pattern are flagged with in_solution=False. A repository
    with a single package is drawn as a folder-level import graph instead.

    When `index` is provided (RepoIndex), uses it for file discovery and reads;
    otherwise falls back to walk_files for backward compatibility.
    """
    repo = Path(repo_path).resolve()

    packages = []
    roots = []

    # Find package.json files via index or walk_files fallback.
    if index is not None:
        package_json_files = [repo / rel for rel in index.by_suffix(".json") if rel.name == "package.json"]
    else:
        package_json_files = list(walk_files(repo, lambda name: name == "package.json"))

    for file in package_json_files:
        data = _parse_json(file, collector) if index is None else index.read_json(file)
        if data is None:
            continue

        directory = file.parent.resolve()
        relative_dir = directory.relative_to(repo).as_posix()
        relative_dir = "" if relative_dir == "." else relative_dir

        globs = _workspace_globs(directory, data)
        if globs:
            roots.append((relative_dir, globs, file))
            continue

        packages.append({
            "name": data.get("name") or directory.name,
            "path": file.resolve(),
            "relative_path": file.relative_to(repo).as_posix(),
            "relative_dir": relative_dir,
            "group": project_group(file.relative_to(repo).as_posix()),
            "ecosystem": "Node.js",
            "data": data,
        })

    # A lone package says nothing as one node; draw its folders instead.
    if len(packages) == 1 and not roots:
        modules = module_projects(repo, packages[0]["path"].parent)
        if modules:
            return {"solutions": [], "projects": modules}

    by_name = {package["name"]: package["path"] for package in packages}

    projects = []
    for package in packages:
        references = []

        for field in DEPENDENCY_FIELDS:
            for name, spec in (package["data"].get(field) or {}).items():
                if name in by_name:
                    target = by_name[name]
                elif isinstance(spec, str) and LOCAL_SPEC.match(spec):
                    target = name
                else:
                    continue  # third-party package

                if target != package["path"] and target not in references:
                    references.append(target)

        in_solution = (
            any(_matches_workspace(package["relative_dir"], root, globs) for root, globs, _ in roots)
            if roots else None
        )

        projects.append({
            key: package[key]
            for key in ("name", "path", "relative_path", "group", "ecosystem")
        } | {"in_solution": in_solution, "references": references})

    return {
        "solutions": [file.relative_to(repo).as_posix() for _, _, file in roots],
        "projects": projects,
    }
