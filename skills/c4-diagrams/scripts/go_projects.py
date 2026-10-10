import re
from pathlib import Path

try:
    from scripts.repo_index import walk_files
    from scripts.paths import project_group
    from scripts.code_facts import go_imports
except ImportError:
    from repo_index import walk_files
    from paths import project_group
    from code_facts import go_imports


MODULE = re.compile(r"^module\s+(\S+)", re.MULTILINE)
REQUIRE = re.compile(r"^\s*(?:require\s+)?([\w.\-/]+)\s+v[\w.\-+]+", re.MULTILINE)
EXPANDED = ("cmd", "internal", "pkg", "api", "app", "services")


def _go_file_text(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _go_files(directory, index=None):
    directory = Path(directory).resolve()
    if index is not None:
        return [f for f in index.walk(lambda n: n.endswith(".go") and not n.endswith("_test.go"))
                if f.parent.resolve().is_relative_to(directory)]
    return [f for f in walk_files(directory, lambda n: n.endswith(".go") and not n.endswith("_test.go"))]


def _package_group(relative_dir):
    """cmd/api/handlers -> cmd/api; internal/store/sql -> internal/store; web/x -> web; "." -> (root)."""
    parts = Path(relative_dir).parts
    if not parts or parts == (".",):
        return "."
    if parts[0] in EXPANDED and len(parts) > 1:
        return "/".join(parts[:2])
    return parts[0]


def _modules(repo, index=None):
    modules = []
    if index is not None:
        candidates = index.walk(lambda n: n == "go.mod")
    else:
        candidates = walk_files(repo, lambda n: n == "go.mod")
    for go_mod in candidates:
        match = MODULE.search(_go_file_text(go_mod))
        if match:
            modules.append({"path": match.group(1), "dir": go_mod.parent.resolve(), "file": go_mod.resolve()})
    return modules


def discover_projects(repo_path, index=None, collector=None):
    """
    Go projects for the dependency graph.

    Several go.mod files: each module is a node, edges from `require` lines
    naming another module in the repo. One go.mod: nodes are package groups
    (cmd/<x>, internal/<x>, pkg/<x>, or top-level folders), edges from imports.

    The `index` parameter is accepted for API compatibility but not yet used.
    Pass a DiagnosticsCollector to route warnings through the diagnostics channel.
    """
    repo = Path(repo_path).resolve()
    modules = _modules(repo, index)
    if not modules:
        return {"solutions": [], "projects": []}

    if len(modules) > 1:
        by_path = {m["path"]: m["file"] for m in modules}
        projects = []
        for m in modules:
            requires = {r for r in REQUIRE.findall(_go_file_text(m["file"])) if r in by_path and r != m["path"]}
            relative = m["file"].relative_to(repo).as_posix()
            projects.append({
                "name": m["path"].rsplit("/", 1)[-1], "path": m["file"], "relative_path": relative,
                "group": project_group(relative), "ecosystem": "Go", "in_solution": None,
                "references": sorted(by_path[r] for r in requires),
            })
        return {"solutions": [], "projects": projects}

    module = modules[0]
    groups = {}
    for file in _go_files(module["dir"], index):
        relative = file.parent.relative_to(module["dir"]).as_posix()
        groups.setdefault(_package_group(relative), []).append(file)

    if len(groups) < 2:
        relative = module["file"].relative_to(repo).as_posix()
        return {"solutions": [], "projects": [{
            "name": module["path"].rsplit("/", 1)[-1], "path": module["file"], "relative_path": relative,
            "group": project_group(relative), "ecosystem": "Go", "in_solution": None, "references": [],
        }]}

    group_dir = {g: (module["dir"] / g).resolve() if g != "." else module["dir"] for g in groups}
    projects = []
    for group, files in sorted(groups.items()):
        targets = set()
        for file in files:
            for imported in go_imports(_go_file_text(file)):
                if not imported.startswith(module["path"]):
                    continue
                relative = imported[len(module["path"]):].lstrip("/") or "."
                target = _package_group(relative)
                if target in groups and target != group:
                    targets.add(group_dir[target])
        relative = group_dir[group].relative_to(repo).as_posix() if group != "." else module["dir"].relative_to(repo).as_posix()
        projects.append({
            "name": group if group != "." else module["path"].rsplit("/", 1)[-1],
            "path": group_dir[group], "relative_path": relative,
            "group": project_group(relative + "/x"), "ecosystem": "Go", "in_solution": None,
            "references": sorted(targets),
        })
    return {"solutions": [], "projects": projects}


GO_WEB = ("net/http", "github.com/gin-gonic/gin", "github.com/labstack/echo", "github.com/gofiber/fiber",
          "github.com/go-chi/chi", "github.com/gorilla/mux", "google.golang.org/grpc")


def main_packages(repo, index=None):
    """Folders holding `package main` code: [(dir, kind, technology)]."""
    found = []
    for module in _modules(repo, index):
        dirs = {}
        for file in _go_files(module["dir"], index):
            text = _go_file_text(file)
            if re.search(r"^package\s+main\b", text, re.MULTILINE):
                dirs.setdefault(file.parent.resolve(), set()).update(go_imports(text))
        all_imports = set()
        for file in _go_files(module["dir"], index):
            all_imports.update(go_imports(_go_file_text(file)))
        for directory, imports in sorted(dirs.items()):
            web = next((w for w in GO_WEB if any(i == w or i.startswith(w + "/") for i in all_imports)), None)
            uses_server = web and (web != "net/http" or any(
                "ListenAndServe" in _go_file_text(f) for f in _go_files(module["dir"])
            ))
            name = {"github.com/gin-gonic/gin": "Gin", "github.com/labstack/echo": "Echo", "github.com/gofiber/fiber": "Fiber",
                    "github.com/go-chi/chi": "chi", "github.com/gorilla/mux": "gorilla/mux", "google.golang.org/grpc": "gRPC",
                    "net/http": "net/http"}.get(web or "", "")
            found.append((directory, module, "web-api" if uses_server else "app", f"Go, {name}" if uses_server else "Go"))
    return found
