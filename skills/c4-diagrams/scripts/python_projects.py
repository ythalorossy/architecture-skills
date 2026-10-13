"""
Python project discovery: distributions when there are several, modules otherwise.

A repository with more than one pyproject.toml / setup.py / setup.cfg has a
project per distribution, with edges from declared requirements that name
another one. With a single distribution the names say nothing, so the
top-level packages become the projects and their import statements the edges.
A folder with only a requirements.txt counts as a service too.

Where nothing declares anything — no manifest and no requirements file — the
source roots are inferred from the layout instead, behind a noise guard so a
release script in a Go repository is not reported as a Python project. Anything
discovered that way carries ``inferred: True``, and so does a package sitting
beside declared services, because no manifest names it either.
"""
import ast
import re
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

try:
    from scripts.repo_index import is_ignored_dir, read_file_text, RepoIndex
    from scripts.paths import REQUIREMENTS_FILE, TOOLING_DIRS, in_test_dir, project_group
except ImportError:
    from repo_index import is_ignored_dir, read_file_text, RepoIndex
    from paths import REQUIREMENTS_FILE, TOOLING_DIRS, in_test_dir, project_group


MANIFESTS = ("pyproject.toml", "setup.py", "setup.cfg")
REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
SETUP_PY_NAME = re.compile(r"""\bname\s*=\s*['"]([^'"]+)['"]""")
# Top-level test packages next to the production code, probed as packages
# of their own (narrower than paths.TEST_DIRS on purpose).
TEST_PACKAGES = ("test", "tests")


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


def _parse_pyproject(file, collector=None, index=None):
    if tomllib is None:
        if collector:
            collector.parse_error("python_projects", str(file), "Python 3.11+ is required to read pyproject.toml")
        return None, []

    # Through the index, like setup.cfg and setup.py: tolerant decoding, and
    # an unreadable or oddly encoded file is recorded instead of raising.
    text = RepoIndex.ensure(index, file.parent, collector).read_text(file)
    if text is None:
        return None, []

    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as ex:
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


def _parse_setup_cfg(file, collector=None, index=None):
    """Name and install_requires from setup.cfg, read through the index (tolerant I/O)."""
    data = RepoIndex.ensure(index, file.parent, collector).read_ini(file)
    if data is None:
        return None, []
    req_raw = data.get("options", {}).get("install_requires", "")
    return data.get("metadata", {}).get("name"), _requirement_names(req_raw.splitlines())


def _parse_setup_py(file, collector=None, index=None):
    """The package name from setup.py, read through the index (tolerant I/O)."""
    text = RepoIndex.ensure(index, file.parent, collector).read_text(file)
    if text is None:
        return None, []
    match = SETUP_PY_NAME.search(text)
    return (match.group(1) if match else None), []


READERS = {
    "pyproject.toml": _parse_pyproject,
    "setup.cfg": _parse_setup_cfg,
    "setup.py": _parse_setup_py,
}


def _distributions(repo, index=None, collector=None):
    """One entry per directory holding a Python package manifest."""
    by_dir = {}

    index = RepoIndex.ensure(index, repo, collector)
    for file in index.walk(lambda name: name in MANIFESTS):
        name, requirements = READERS[file.name](file, collector, index)
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
            "inferred": False,
            "references": sorted(
                {paths[name] for name in d["requirements"] if name in paths} - {d["file"].resolve()}
            ),
        }
        for d in distributions
    ]


def requirements_services(repo, index=None, packaged=()):
    """
    Folders with their own requirements*.txt and no pyproject.toml/setup.py:
    small services often have only that. One entry each; folders inside a
    packaged distribution, tests and docs are skipped.

    Shared with c4_facts, which turns the same folders into containers, so a
    service is a project and a container by one rule rather than two.
    """
    repo = Path(repo).resolve()
    index = RepoIndex.ensure(index, repo)
    packaged = [Path(directory).resolve() for directory in packaged]

    folders = set()
    for file in index.walk(lambda name: REQUIREMENTS_FILE.match(name)):
        folder = file.parent.resolve()
        parts = [part.lower() for part in folder.relative_to(repo).parts]
        if in_test_dir(parts) or any(part in ("docs", "doc") for part in parts):
            continue
        if any(folder == directory or folder.is_relative_to(directory) for directory in packaged):
            continue
        folders.add(folder)

    return [
        {"name": folder.name if folder != repo else repo.name, "directory": folder, "file": None, "requirements": []}
        for folder in sorted(folders)
    ]


def _is_tooling(path, repo):
    """True for a node under scripts/, tools/, docs/ and the like, or under a test folder."""
    parts = path.relative_to(repo).parts
    return parts[0].lower() in TOOLING_DIRS or in_test_dir(parts)


def _folder_nodes(repo, declared, index=None):
    """
    Node map for the folder-level graph: ``{name: (path, import_root)}``.

    The declared folders (services, distributions) plus the top-level packages
    beside them, which is where a shared library lives in a repository built
    this way. Every node imports against the repository root, so
    ``import shared.models`` in a service resolves to the shared package.
    """
    nodes = {folder["directory"].name: (folder["directory"], repo) for folder in declared}
    owned = [folder["directory"] for folder in declared]

    for path in sorted(repo.iterdir()):
        if not _is_package(path) or path.name in nodes:
            continue
        if _is_tooling(path, repo) or any(path.is_relative_to(directory) for directory in owned):
            continue
        nodes[path.name] = (path, repo)

    return nodes


def inferred_nodes(repo, index=None):
    """
    Source roots for a repository that declares no Python packaging at all.

    ``{name: (path, import_root)}``: the top-level folders holding Python
    source, or the top-level modules when there are no such folders. Empty when
    the repository has a manifest or a requirements file — there is nothing to
    infer then — and empty when the noise guard rejects what is left.

    The guard is what keeps a release script out of a Go repository's report:
    a tooling folder (scripts/, tools/, docs/, ...) and a test folder are never
    a source root, and a single loose module at the repository root is a script
    rather than a program, where two or more side by side are a flat layout.
    """
    repo = Path(repo).resolve()
    index = RepoIndex.ensure(index, repo)

    if any(index.walk(lambda name: name in MANIFESTS or REQUIREMENTS_FILE.match(name))):
        return {}

    folders = sorted(
        path for path in repo.iterdir()
        if path.is_dir() and not is_ignored_dir(path.name)
        and path.name not in TEST_PACKAGES and not _is_tooling(path, repo)
        and _python_files(path, index)
    )
    if folders:
        return {path.name: (path, repo) for path in folders}

    modules = sorted(
        path for path in repo.glob("*.py")
        if path.name not in {"setup.py", "conftest.py", "__init__.py"}
    )
    if len(modules) < 2:
        return {}
    return {path.stem: (path, repo) for path in modules}


def _python_files(path, index=None):
    if path.is_file():
        return [path]
    return list(RepoIndex.ensure(index, path).walk(lambda name: name.endswith(".py"), under=path))


def _module_name(file, import_root):
    parts = list(file.relative_to(import_root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imported_modules(file, import_root, collector=None, index=None):
    """Absolute dotted names imported by a file, with relative imports resolved."""
    source = index.read_text(file) if index is not None else None
    if source is None:
        source = read_file_text(file, "python_projects")
    try:
        tree = ast.parse(source, filename=str(file))
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


def _module_nodes(base, index=None):
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
        if _is_package(path) and path.name not in TEST_PACKAGES
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
        for name in TEST_PACKAGES:
            tests = folder / name
            if tests.is_dir() and _python_files(tests, index):
                nodes.setdefault(name, (tests, folder))

    return nodes


def _module_projects(repo, base, collector=None, index=None):
    return _projects_from_nodes(repo, _module_nodes(base, index), collector, index)


def _projects_from_nodes(repo, nodes, collector=None, index=None, inferred=()):
    """
    One project per node, with an edge wherever a node imports another one.

    ``inferred`` names the nodes no manifest and no requirements file vouches
    for; they are marked so the report can say the layout was read as a guess.
    """
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
        for file in _python_files(path, index):
            for module in _imported_modules(file, import_root, collector, index):
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
            "inferred": name in inferred,
            "references": sorted(targets),
        })

    return projects


def discover_projects(repo_path, index=None, collector=None):
    """
    Python projects for the dependency graph.

    With several distributions (pyproject.toml / setup.py / setup.cfg), each is a
    node and edges come from declared requirements naming another distribution.
    With service folders carrying only a requirements.txt, each folder is a node
    along with the packages beside it, and edges come from import statements.
    With a single distribution and nothing else the names say nothing, so the
    nodes are its packages/modules. With no packaging at all the source roots
    are inferred from the layout, behind the guard in ``inferred_nodes``.

    Uses `index` (a RepoIndex) for discovery and reads; one is built when none is passed.
    Pass a DiagnosticsCollector to route warnings through the diagnostics channel.
    """
    repo = Path(repo_path).resolve()

    index = RepoIndex.ensure(index, repo, collector)
    has_manifest = any(index.walk(lambda name: name in MANIFESTS or REQUIREMENTS_FILE.match(name)))
    if not has_manifest:
        nodes = inferred_nodes(repo, index)
        projects = _projects_from_nodes(repo, nodes, collector, index, inferred=set(nodes))
        return {"solutions": [], "projects": projects}

    distributions = _distributions(repo, index, collector)
    services = requirements_services(repo, index, [d["directory"] for d in distributions])

    if services:
        # A repository of service folders: the folders are the nodes, and so
        # are the packages beside them, which is where the shared code lives.
        nodes = _folder_nodes(repo, services + distributions, index)
        declared = {folder["directory"].name for folder in services + distributions}
        projects = _projects_from_nodes(repo, nodes, collector, index, inferred=set(nodes) - declared)
    elif len(distributions) > 1:
        projects = _distribution_projects(repo, distributions)
    else:
        base = distributions[0]["directory"] if distributions else repo
        projects = _module_projects(repo, base, collector, index)

    return {"solutions": [], "projects": projects}
