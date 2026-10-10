import ast
import configparser
import re
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

try:
    from scripts.repo_index import is_ignored_dir, walk_files
    from scripts.paths import project_group
except ImportError:
    from repo_index import is_ignored_dir, walk_files
    from paths import project_group


MANIFESTS = ("pyproject.toml", "setup.py", "setup.cfg")
REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
SETUP_PY_NAME = re.compile(r"""\bname\s*=\s*['"]([^'"]+)['"]""")
TEST_DIRS = {"test", "tests"}


def normalize(name):
    """PEP 503 name normalization, so My_Pkg and my-pkg match."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_names(requirements):
    names = []
    for requirement in requirements or []:
        match = REQUIREMENT_NAME.match(requirement) if isinstance(requirement, str) else None
        if match:
            names.append(normalize(match.group(1)))
    return names


def _parse_pyproject(file, collector=None):
    if tomllib is None:
        if collector:
            collector.parse_error("python_projects", str(file), "Python 3.11+ is required to read pyproject.toml")
        return None, []

    try:
        data = tomllib.loads(file.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as ex:
        if collector:
            collector.parse_error("python_projects", str(file), f"invalid TOML: {ex}")
        return None, []

    project = data.get("project", {})
    poetry = data.get("tool", {}).get("poetry", {})

    requirements = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        requirements += extra
    for group in data.get("dependency-groups", {}).values():
        requirements += [item for item in group if isinstance(item, str)]

    names = _requirement_names(requirements)
    names += [normalize(name) for name in poetry.get("dependencies", {})]
    for group in poetry.get("group", {}).values():
        names += [normalize(name) for name in group.get("dependencies", {})]

    return project.get("name") or poetry.get("name"), names


def _parse_setup_cfg(file, collector=None):
    parser = configparser.ConfigParser()
    try:
        parser.read(file, encoding="utf-8")
    except configparser.Error:
        return None, []
    requirements = parser.get("options", "install_requires", fallback="").splitlines()
    return parser.get("metadata", "name", fallback=None), _requirement_names(requirements)


def _parse_setup_py(file, collector=None):
    match = SETUP_PY_NAME.search(file.read_text(encoding="utf-8", errors="replace"))
    return (match.group(1) if match else None), []


READERS = {
    "pyproject.toml": _parse_pyproject,
    "setup.cfg": _parse_setup_cfg,
    "setup.py": _parse_setup_py,
}


def _distributions(repo, index=None, collector=None):
    """One entry per directory holding a Python package manifest."""
    by_dir = {}

    if index is not None:
        candidates = index.walk(lambda name: name in MANIFESTS)
    else:
        candidates = walk_files(repo, lambda name: name in MANIFESTS)
    for file in candidates:
        name, requirements = READERS[file.name](file, collector)
        # A pyproject.toml without a name only holds tool config (ruff, a uv
        # workspace root, ...); it does not make its folder a package.
        if file.name == "pyproject.toml" and not name:
            continue

        entry = by_dir.setdefault(file.parent.resolve(), {"name": None, "requirements": [], "file": file})
        entry["name"] = entry["name"] or name
        entry["requirements"] += requirements
        if file.name == "pyproject.toml":
            entry["file"] = file

    return [
        {**entry, "directory": directory, "name": entry["name"] or directory.name}
        for directory, entry in by_dir.items()
    ]


def _distribution_projects(repo, distributions):
    paths = {normalize(d["name"]): d["file"].resolve() for d in distributions}

    return [
        {
            "name": d["name"],
            "path": d["file"].resolve(),
            "relative_path": d["file"].relative_to(repo).as_posix(),
            "group": project_group(d["file"].relative_to(repo).as_posix()),
            "ecosystem": "Python",
            "in_solution": None,
            "references": sorted(
                {paths[name] for name in d["requirements"] if name in paths} - {d["file"].resolve()}
            ),
        }
        for d in distributions
    ]


def _python_files(path, index=None):
    if path.is_file():
        return [path]
    if index is not None:
        return list(index.walk(lambda name: name.endswith(".py")))
    return list(walk_files(path, lambda name: name.endswith(".py")))


def _module_name(file, import_root):
    parts = list(file.relative_to(import_root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imported_modules(file, import_root, collector=None):
    """Absolute dotted names imported by a file, with relative imports resolved."""
    try:
        tree = ast.parse(file.read_text(encoding="utf-8", errors="replace"), filename=str(file))
    except (SyntaxError, ValueError) as ex:
        if collector:
            collector.parse_error("python_projects", str(file), f"syntax error: {ex}")
        return []

    package = _module_name(file, import_root).split(".")
    if file.name != "__init__.py":
        package = package[:-1]

    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package[:len(package) - node.level + 1]
                base = ".".join(anchor + ([base] if base else []))
            # `from pkg import sub` may import a submodule, so try that first.
            modules += [f"{base}.{alias.name}" for alias in node.names] + [base]
    return modules


def _is_package(path):
    return path.is_dir() and not is_ignored_dir(path.name) and (path / "__init__.py").exists()


def _module_nodes(base):
    """
    Map node name -> (path, import root).

    Nodes are the top-level packages of the import root (base/src if it exists,
    else base), or its top-level modules when it has no packages, plus a
    tests/ folder found in either place. A codebase with a
    single top-level package is drawn one level deeper, as its subpackages and
    modules, since a one-node graph says nothing.
    """
    import_root = base / "src" if (base / "src").is_dir() else base

    production = sorted(
        path for path in import_root.iterdir()
        if _is_package(path) and path.name not in TEST_DIRS
    )

    if not production:
        # Flat layout: no packages, just modules side by side.
        production = sorted(
            path for path in import_root.glob("*.py")
            if path.name not in {"setup.py", "conftest.py", "__init__.py"}
        )
    elif len(production) == 1:
        package = production[0]
        production = sorted(
            child for child in package.iterdir()
            if _is_package(child) or (child.suffix == ".py" and child.name != "__init__.py")
        ) or [package]

    nodes = {_module_name(path, import_root): (path, import_root) for path in production}

    for folder in {import_root, base}:
        for name in TEST_DIRS:
            tests = folder / name
            if tests.is_dir() and _python_files(tests):
                nodes.setdefault(name, (tests, folder))

    return nodes


def _module_projects(repo, base, collector=None):
    nodes = _module_nodes(base)
    if not nodes:
        return []

    def owner(module):
        # Longest node name that is the module itself or a parent of it.
        parts = module.split(".")
        for size in range(len(parts), 0, -1):
            name = ".".join(parts[:size])
            if name in nodes:
                return name
        return None

    projects = []
    for name, (path, import_root) in nodes.items():
        targets = set()
        for file in _python_files(path):
            for module in _imported_modules(file, import_root, collector):
                target = owner(module)
                if target and target != name:
                    targets.add(nodes[target][0].resolve())

        relative = path.relative_to(repo).as_posix()
        projects.append({
            "name": name,
            "path": path.resolve(),
            "relative_path": relative,
            "group": project_group(relative),
            "ecosystem": "Python",
            "in_solution": None,
            "references": sorted(targets),
        })

    return projects


def discover_projects(repo_path, index=None, collector=None):
    """
    Python projects for the dependency graph.

    With several distributions (pyproject.toml / setup.py / setup.cfg), each is a
    node and edges come from declared requirements naming another distribution.
    Otherwise nodes are packages/modules and edges come from import statements.
    Nothing is returned unless the repository has a Python manifest.

    The `index` parameter is accepted for API compatibility but not yet used.
    Pass a DiagnosticsCollector to route warnings through the diagnostics channel.
    """
    repo = Path(repo_path).resolve()

    if index is not None:
        has_manifest = any(index.walk(lambda name: name in MANIFESTS or re.match(r"requirements.*\.txt$", name)))
    else:
        has_manifest = any(walk_files(
            repo,
            lambda name: name in MANIFESTS or re.match(r"requirements.*\.txt$", name)
        ))
    if not has_manifest:
        return {"solutions": [], "projects": []}

    distributions = _distributions(repo, index, collector)
    if len(distributions) > 1:
        projects = _distribution_projects(repo, distributions)
    else:
        base = distributions[0]["directory"] if distributions else repo
        projects = _module_projects(repo, base, collector)

    return {"solutions": [], "projects": projects}
