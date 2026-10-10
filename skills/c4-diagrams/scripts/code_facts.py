"""
Language-neutral facts for the report, beyond the C4 elements:

- code_components: inside each module, its packages/namespaces and the
  imports between them (Java, Kotlin, C#, Go);
- endpoints: HTTP routes declared in code (Spring, JAX-RS, ASP.NET, Express,
  Fastify, Koa, NestJS, FastAPI, Flask, Django, Go net/http, gin, echo, chi);
- deployment: docker-compose services, Dockerfiles, Kubernetes manifests, CI;
- configuration: environment variables read by the code or set by compose;
- inventory: runtime, frameworks and key libraries with versions per container;
- dev_proxies: front-end dev servers that forward calls to a back end.

Every item has repo-relative file:line evidence.
"""
import json
import re
from pathlib import Path

try:
    from scripts.repo_index import walk_files, local_tag
except ImportError:
    from repo_index import walk_files, local_tag
import xml.etree.ElementTree as ET


TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "e2e", "testdata"}
CODE_EXTENSIONS = {".java": "jvm", ".kt": "jvm", ".cs": "cs", ".go": "go"}


def _file_text(path):
    try:
        return Path(path).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def _line_of(text, index):
    return text.count("\n", 0, index) + 1


def _rel(repo, path):
    return Path(path).resolve().relative_to(repo).as_posix()


def _is_test(path, base):
    parts = Path(path).relative_to(base).parts[:-1]
    name = Path(path).name
    return (
        any(part.lower() in TEST_DIRS for part in parts)
        or re.search(r"(Tests?|Spec)\.(java|kt|cs)$|_test\.go$", name) is not None
    )


# ---------- code components (packages / namespaces inside modules) ----------

JVM_PACKAGE = re.compile(r"^\s*package\s+([\w.]+)", re.MULTILINE)
JVM_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)", re.MULTILINE)
CS_NAMESPACE = re.compile(r"^\s*namespace\s+([\w.]+)", re.MULTILINE)
CS_USING = re.compile(r"^\s*(?:global\s+)?using\s+(?:static\s+)?([\w.]+)\s*;", re.MULTILINE)
GO_IMPORT_BLOCK = re.compile(r"^\s*import\s*\(([^)]*)\)", re.MULTILINE | re.DOTALL)
GO_IMPORT_LINE = re.compile(r'^\s*import\s+(?:\w+\s+)?"([^"]+)"', re.MULTILINE)
GO_QUOTED = re.compile(r'"([^"]+)"')


def go_imports(text):
    found = [m.group(1) for m in GO_IMPORT_LINE.finditer(text)]
    for block in GO_IMPORT_BLOCK.finditer(text):
        found += GO_QUOTED.findall(block.group(1))
    return found


def _go_module_path(directory):
    for folder in [directory, *directory.parents]:
        go_mod = folder / "go.mod"
        if go_mod.is_file():
            match = re.search(r"^module\s+(\S+)", _file_text(go_mod), re.MULTILINE)
            return (match.group(1), folder) if match else (None, folder)
    return None, None


def _module_packages(module_dir, index=None):
    """{file: (language, package, [imports])} for the JVM/C#/Go code of one module, tests excluded."""
    files = {}
    if index is not None:
        candidates = [f for f in index.walk(lambda name: Path(name).suffix in CODE_EXTENSIONS)
                     if f.parent.resolve().is_relative_to(module_dir.resolve())]
    else:
        candidates = walk_files(module_dir, lambda name: Path(name).suffix in CODE_EXTENSIONS)
    for file in candidates:
        if _is_test(file, module_dir):
            continue
        language = CODE_EXTENSIONS[file.suffix]
        text = _file_text(file)
        if language == "jvm":
            match = JVM_PACKAGE.search(text)
            package = match.group(1) if match else ""
            imports = [i.rstrip(".") for i in JVM_IMPORT.findall(text)]
        elif language == "cs":
            match = CS_NAMESPACE.search(text)
            package = match.group(1) if match else ""
            imports = CS_USING.findall(text)
        else:
            module_path, root = _go_module_path(file.parent)
            if not module_path:
                continue
            relative = file.parent.relative_to(root).as_posix()
            package = module_path if relative == "." else f"{module_path}/{relative}"
            imports = go_imports(text)
        files[file] = (language, package, imports)
    return files


def _split(package, language):
    return package.split("/") if language == "go" else package.split(".")


def _join(parts, language):
    return ("/" if language == "go" else ".").join(parts)


def _majority_root(split_packages, weights):
    """Longest prefix shared by at least 70% of the files (one odd package can't flatten the tree)."""
    total = sum(weights)
    root = []
    while True:
        counts = {}
        for parts, weight in zip(split_packages, weights):
            if len(parts) > len(root) and parts[:len(root)] == root:
                counts[parts[len(root)]] = counts.get(parts[len(root)], 0) + weight
        if not counts:
            return root
        segment, count = max(counts.items(), key=lambda item: item[1])
        if count < 0.7 * total:
            return root
        root = root + [segment]


def code_components(module_dirs, index=None):
    """
    Package-level graph across the given modules: {"nodes": {id: {...}}, "edges": {id: [ids]}}.

    module_dirs maps a module (component) name to its folder. Grouping per language:
    - Java/Kotlin: the first package segment below the module's root package
      (io.acme.api.controller -> "controller"); the root is the prefix most files share;
    - C#: the top-level folder inside the project (Controllers, Services, Features...),
      since folders are the reliable unit in .NET; `using` statements are mapped to
      folders through the namespaces declared in them;
    - Go: the package folder below the module root (cmd/api, internal/store).
    Returns None when no module has JVM, C# or Go code.
    """
    nodes, file_owner, imports_of = {}, {}, {}
    namespace_votes = {}

    for module, directory in module_dirs.items():
        files = _module_packages(directory, index)
        if not files:
            continue
        languages = [language for language, _, _ in files.values()]
        language = max(set(languages), key=languages.count)

        if language == "jvm":
            split = {f: _split(pkg, "jvm") for f, (_, pkg, _) in files.items() if pkg}
            root = _majority_root(list(split.values()), [1] * len(split))
            if root and all(parts == root for parts in split.values()):
                root = root[:-1]  # one package only: name it after itself

        for file, (_, package, imports) in files.items():
            if language == "cs":
                relative = file.relative_to(directory).parts
                group = relative[0] if len(relative) > 1 else "(root)"
                path = "/".join(relative[:1]) if len(relative) > 1 else "."
            elif language == "go":
                module_path = package.split("/")
                _, go_root = _go_module_path(file.parent)
                relative = file.parent.relative_to(go_root).parts if go_root else ()
                if relative[:1] and relative[0] in ("cmd", "internal", "pkg", "api", "app") and len(relative) > 1:
                    group = "/".join(relative[:2])
                else:
                    group = relative[0] if relative else "(root)"
                path = group
            else:
                parts = _split(package, "jvm") if package else []
                below = parts[len(root):] if parts[:len(root)] == root else parts
                group = below[0] if below else "(root)"
                path = _join(root + ([group] if group != "(root)" else []), "jvm")

            node = f"{module}::{group}"
            entry = nodes.setdefault(node, {
                "module": module, "group": module, "label": group, "language": language,
                "path": path, "files": 0,
            })
            entry["files"] += 1
            if package:
                votes = namespace_votes.setdefault(package, {})
                votes[node] = votes.get(node, 0) + 1
            file_owner[file.resolve()] = node
            imports_of.setdefault(node, set()).update(imports)

    if len(nodes) < 2:
        return None

    # Each package/namespace belongs to the node that holds most of its files.
    package_owner = {pkg: max(votes.items(), key=lambda v: v[1])[0] for pkg, votes in namespace_votes.items()}
    known = sorted(package_owner, key=len, reverse=True)
    edges = {node: set() for node in nodes}
    for node, imports in imports_of.items():
        for name in imports:
            target = package_owner.get(name)
            if target is None:
                # Class import (a.b.C) or a parent/child namespace: longest known package prefix.
                target = next(
                    (package_owner[p] for p in known if name.startswith(p + ".") or name.startswith(p + "/")),
                    None,
                )
            if target and target != node:
                edges[node].add(target)

    return {
        "nodes": dict(sorted(nodes.items())),
        "edges": {node: sorted(targets) for node, targets in sorted(edges.items())},
        "_files": file_owner,  # file -> node, used to place stores/externals; not written out
    }


# ---------- HTTP endpoints ----------

HTTP_METHODS = ("get", "post", "put", "delete", "patch", "head", "options")
_STR = r"""['"`]([^'"`]*)['"`]"""

SPRING_CLASS = re.compile(r"@RequestMapping\s*\(\s*(?:(?:value|path)\s*=\s*)?\{?\s*\"([^\"]*)\"")
SPRING_METHOD = re.compile(r"@(Get|Post|Put|Delete|Patch)Mapping\s*(?:\(\s*(?:(?:value|path)\s*=\s*)?\{?\s*(?:\"([^\"]*)\")?[^)]*\))?")
JAXRS_PATH = re.compile(r"@Path\s*\(\s*\"([^\"]*)\"\s*\)")
JAXRS_METHOD = re.compile(r"@(GET|POST|PUT|DELETE|PATCH)\b")
CS_ROUTE = re.compile(r"\[Route\s*\(\s*\"([^\"]*)\"")
CS_HTTP = re.compile(r"\[Http(Get|Post|Put|Delete|Patch)\s*(?:\(\s*\"([^\"]*)\")?")
CS_CLASS = re.compile(r"class\s+(\w+?)(?:Controller)?\b")
# MVC controllers without [Route] use conventional routing: every public method is an action.
CS_CONTROLLER = re.compile(r"\b(abstract\s+)?(?:partial\s+)?class\s+(\w+?)Controller\b")
CS_ACTION = re.compile(
    r"^[ \t]*public\s+(?!static\b|class\b|abstract\b)(?:(?:async|virtual|override|new)\s+)*[\w<>\[\],.? ]+?\s+(\w+)\s*\(",
    re.MULTILINE
)
CS_ATTRIBUTES = re.compile(r"(?:^[ \t]*\[[^\n]*\][ \t]*(?://[^\n]*)?\r?\n)+\Z", re.MULTILINE)
# Attributes can share brackets ([HttpPost, ActionName("x")]), so these don't require a leading "[".
CS_ACTION_HTTP = re.compile(r"\bHttp(Get|Post|Put|Delete|Patch)\b\s*(?:\(\s*\"([^\"]*)\")?")
CS_ACTION_NAME = re.compile(r"\bActionName\s*\(\s*\"([^\"]+)\"")
CS_MINIMAL = re.compile(r"\.Map(Get|Post|Put|Delete|Patch)\s*\(\s*\"([^\"]*)\"")
JS_ROUTE = re.compile(r"\b(?:app|router|server|api|routes|fastify|r)\s*\.\s*(" + "|".join(HTTP_METHODS) + r")\s*\(\s*" + _STR)
NEST_CONTROLLER = re.compile(r"@Controller\s*\(\s*(?:" + _STR + r")?")
NEST_METHOD = re.compile(r"@(Get|Post|Put|Delete|Patch)\s*\(\s*(?:" + _STR + r")?\s*\)")
PY_DECORATOR = re.compile(r"@\s*(\w+)\.(" + "|".join(HTTP_METHODS) + r")\s*\(\s*['\"]([^'\"]*)['\"]")
PY_ROUTE = re.compile(r"@\s*\w+\.route\s*\(\s*['\"]([^'\"]*)['\"](?:[^)]*methods\s*=\s*\[([^\]]*)\])?")
PY_ROUTER_PREFIX = re.compile(r"(\w+)\s*=\s*APIRouter\s*\([^)]*prefix\s*=\s*['\"]([^'\"]*)['\"]")
DJANGO_PATH = re.compile(r"\b(?:re_)?path\s*\(\s*r?['\"]([^'\"]*)['\"]")
GO_HANDLE = re.compile(r"\.(?:HandleFunc|Handle)\s*\(\s*\"([^\"]*)\"")
GO_ROUTER = re.compile(r"\.(GET|POST|PUT|DELETE|PATCH|Get|Post|Put|Delete|Patch)\s*\(\s*\"(/[^\"]*)\"")


def _join_path(prefix, path):
    joined = "/" + "/".join(part.strip("/") for part in (prefix, path) if part and part.strip("/"))
    return joined if joined != "/" or not (prefix or path) else "/"


def _conventional_actions(text):
    """[(method, path, index)] for an MVC controller routed by {controller}/{action}."""
    controller = CS_CONTROLLER.search(text)
    if controller.group(1):
        return []
    name = controller.group(2)
    found = []
    for m in CS_ACTION.finditer(text, controller.end()):
        action = m.group(1)
        if action == name + "Controller":
            continue
        attributes = CS_ATTRIBUTES.search(text, 0, m.start())
        attributes = attributes.group(0) if attributes else ""
        if re.search(r"\bNonAction\b", attributes):
            continue
        renamed = CS_ACTION_NAME.search(attributes)
        path = f"/{name}/{renamed.group(1) if renamed else action}"
        verbs = CS_ACTION_HTTP.findall(attributes)
        for verb, template in verbs or [("ANY", None)]:
            found.append((verb.upper(), "/" + template.lstrip("/~") if template else path, m.start()))
    return found


def _endpoints_in(text, suffix):
    """[(method, path, index)] declared in one source file."""
    found = []
    if suffix in (".java", ".kt"):
        class_prefix = ""
        class_match = SPRING_CLASS.search(text)
        first_method = SPRING_METHOD.search(text)
        if class_match and (not first_method or class_match.start() < first_method.start()):
            class_prefix = class_match.group(1)
        for m in SPRING_METHOD.finditer(text):
            found.append((m.group(1).upper(), _join_path(class_prefix, m.group(2) or ""), m.start()))
        if "javax.ws.rs" in text or "jakarta.ws.rs" in text:
            paths = list(JAXRS_PATH.finditer(text))
            base = paths[0].group(1) if paths else ""
            for m in JAXRS_METHOD.finditer(text):
                local = next((p.group(1) for p in paths[1:] if 0 < m.start() - p.start() < 300 or 0 < p.start() - m.start() < 300), "")
                found.append((m.group(1), _join_path(base, local), m.start()))
    elif suffix == ".cs" and not CS_ROUTE.search(text) and CS_CONTROLLER.search(text):
        found.extend(_conventional_actions(text))
        for m in CS_MINIMAL.finditer(text):
            found.append((m.group(1).upper(), m.group(2), m.start()))
    elif suffix == ".cs":
        routes = list(CS_ROUTE.finditer(text))
        class_name = CS_CLASS.search(text)
        controller = (class_name.group(1) if class_name else "").lower()
        prefix = routes[0].group(1) if routes else ""
        for m in CS_HTTP.finditer(text):
            path = m.group(2)
            if path is None:
                local = next((r.group(1) for r in routes[1:] if 0 < m.start() - r.start() < 200 or 0 < r.start() - m.start() < 200), "")
                path = local
            full = path if path.startswith("/") or path.startswith("~") else _join_path(prefix, path)
            found.append((m.group(1).upper(), full.replace("[controller]", controller).lstrip("~"), m.start()))
        for m in CS_MINIMAL.finditer(text):
            found.append((m.group(1).upper(), m.group(2), m.start()))
    elif suffix in (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"):
        for m in JS_ROUTE.finditer(text):
            if m.group(2).startswith("/"):
                found.append((m.group(1).upper(), m.group(2), m.start()))
        controller = NEST_CONTROLLER.search(text)
        if controller:
            prefix = controller.group(1) or ""
            for m in NEST_METHOD.finditer(text):
                found.append((m.group(1).upper(), _join_path(prefix, m.group(2) or ""), m.start()))
    elif suffix == ".py":
        prefixes = dict(PY_ROUTER_PREFIX.findall(text))
        for m in PY_DECORATOR.finditer(text):
            found.append((m.group(2).upper(), _join_path(prefixes.get(m.group(1), ""), m.group(3)), m.start()))
        for m in PY_ROUTE.finditer(text):
            methods = re.findall(r"['\"](\w+)['\"]", m.group(2) or "") or ["GET"]
            for method in methods:
                found.append((method.upper(), m.group(1) or "/", m.start()))
        if "urlpatterns" in text:
            for m in DJANGO_PATH.finditer(text):
                found.append(("ANY", "/" + m.group(1).lstrip("^/"), m.start()))
    elif suffix == ".go":
        for m in GO_HANDLE.finditer(text):
            found.append(("ANY", m.group(1), m.start()))
        for m in GO_ROUTER.finditer(text):
            found.append((m.group(1).upper(), m.group(2), m.start()))
    return found


def endpoints(repo, files, owner_of):
    """[{method, path, file, line, container}] from source files; owner_of(file) gives the container id."""
    result, seen = [], set()
    for file in files:
        if file.suffix not in (".java", ".kt", ".cs", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".py", ".go"):
            continue
        text = _file_text(file)
        for method, path, index in _endpoints_in(text, file.suffix):
            key = (method, path, file)
            if key in seen:
                continue
            seen.add(key)
            result.append({
                "method": method, "path": path or "/",
                "file": _rel(repo, file), "line": _line_of(text, index),
                "container": owner_of(file),
            })
    return sorted(result, key=lambda e: (e["container"] or "", e["path"], e["method"]))


# ---------- deployment ----------

def _yaml_block(lines, start, indent):
    """Lines of a YAML block that starts after `start` and is indented more than `indent`."""
    block = []
    for line in lines[start:]:
        if line.strip() and not line.lstrip().startswith("#"):
            if len(line) - len(line.lstrip()) <= indent:
                break
        block.append(line)
    return block


def compose_services(index):
    """Every docker-compose service with image, build, ports, depends_on and environment keys."""
    services = []
    repo = index.root
    for file in index.walk(lambda name: re.match(r"(docker-)?compose(\.[\w-]+)?\.ya?ml$", name)):
        lines = _file_text(file).splitlines()
        in_services, service_indent, current, key_indent = False, None, None, None
        section = None
        for number, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(line) - len(line.lstrip())
            if indent == 0:
                in_services = line.startswith("services:")
                current = None
                continue
            if not in_services:
                continue
            if service_indent is None:
                service_indent = indent
            if indent == service_indent:
                current = {
                    "name": stripped.rstrip(":"), "image": None, "build": None, "ports": [],
                    "depends_on": [], "environment": {}, "file": _rel(repo, file), "line": number,
                    "dir": file.parent.resolve(),
                }
                services.append(current)
                key_indent, section = None, None
                continue
            if current is None:
                continue
            if key_indent is None:
                key_indent = indent
            if indent == key_indent:
                key, _, value = stripped.partition(":")
                value = value.strip().strip("'\"")
                section = key
                if key == "image":
                    current["image"] = value
                elif key == "build" and value:
                    current["build"] = value
                elif key == "build":
                    current["build"] = "."
                continue
            item = re.sub(r"\s+#.*$", "", stripped).lstrip("- ").strip()
            if section == "build" and item.startswith("context:"):
                current["build"] = item.partition(":")[2].strip().strip("'\"")
            elif section == "ports":
                current["ports"].append(item.strip("'\""))
            elif section == "depends_on":
                name = item.rstrip(":").strip("'\"")
                if indent == key_indent + 2 or stripped.startswith("-"):
                    current["depends_on"].append(name)
            elif section == "environment":
                if "=" in item and ":" not in item.split("=")[0]:
                    key, _, value = item.partition("=")
                else:
                    key, _, value = item.partition(":")
                current["environment"][key.strip().strip("'\"")] = value.strip().strip("'\"")
    return services


def _dockerfiles(index):
    result = []
    repo = index.root
    for file in index.walk(lambda name: name == "Dockerfile" or name.endswith(".Dockerfile") or name.startswith("Dockerfile.")):
        text = _file_text(file)
        stages = re.findall(r"^\s*FROM\s+(\S+)", text, re.MULTILINE | re.IGNORECASE)
        exposed = re.findall(r"^\s*EXPOSE\s+(.+)$", text, re.MULTILINE | re.IGNORECASE)
        entry = re.findall(r"^\s*(?:ENTRYPOINT|CMD)\s+(.+)$", text, re.MULTILINE | re.IGNORECASE)
        result.append({
            "file": _rel(repo, file),
            "base_images": stages,
            "runtime_image": stages[-1] if stages else None,
            "expose": " ".join(e.strip() for e in exposed),
            "entrypoint": entry[-1].strip() if entry else None,
        })
    return result


def _kubernetes(index):
    result = []
    repo = index.root
    for file in index.walk(lambda name: name.endswith((".yaml", ".yml"))):
        text = _file_text(file)
        if "apiVersion:" not in text or "kind:" not in text:
            continue
        for document in re.split(r"^---\s*$", text, flags=re.MULTILINE):
            kind = re.search(r"^kind:\s*(\w+)", document, re.MULTILINE)
            name = re.search(r"^metadata:\s*\n(?:\s+.*\n)*?\s+name:\s*(\S+)", document, re.MULTILINE)
            if not kind or kind.group(1) not in ("Deployment", "StatefulSet", "DaemonSet", "Service", "Ingress", "CronJob", "Job"):
                continue
            result.append({
                "kind": kind.group(1),
                "name": name.group(1).strip("'\"") if name else "?",
                "images": re.findall(r"^\s*image:\s*(\S+)", document, re.MULTILINE),
                "file": _rel(repo, file),
            })
    return result


CI_FILES = [
    (".github/workflows", "GitHub Actions"), (".gitlab-ci.yml", "GitLab CI"), ("azure-pipelines", "Azure Pipelines"),
    (".azure", "Azure Pipelines"), ("Jenkinsfile", "Jenkins"), (".circleci", "CircleCI"), ("bitbucket-pipelines.yml", "Bitbucket Pipelines"),
]
PLATFORM_FILES = [
    ("fly.toml", "Fly.io"), ("vercel.json", "Vercel"), ("netlify.toml", "Netlify"), ("Procfile", "Heroku-style Procfile"),
    ("serverless.yml", "Serverless Framework"), ("app.yaml", "Google App Engine"), ("render.yaml", "Render"),
    ("Chart.yaml", "Helm chart"), ("kustomization.yaml", "Kustomize"), ("main.tf", "Terraform"), ("template.yaml", "AWS SAM"),
    ("bicep", "Azure Bicep"),
]


def deployment(index):
    ci, platforms = [], []
    repo = index.root
    for path in sorted(index.walk(lambda n: True)):
        if any(part in ("node_modules", ".git", "bin", "obj", "target", "dist") for part in path.parts):
            continue
        relative = path.relative_to(repo).as_posix()
        for marker, name in CI_FILES:
            if (relative == marker or relative.startswith(marker + "/")) and path.is_file():
                ci.append({"tool": name, "file": relative})
        for marker, name in PLATFORM_FILES:
            if path.is_file() and (path.name == marker or (marker == "bicep" and path.suffix == ".bicep")):
                platforms.append({"tool": name, "file": relative})
    return {
        "compose": [
            {k: v for k, v in s.items() if k != "dir"} for s in compose_services(index)
        ],
        "dockerfiles": _dockerfiles(index),
        "kubernetes": _kubernetes(index),
        "ci": ci,
        "platforms": platforms,
    }


# ---------- configuration ----------

ENV_PATTERNS = [
    re.compile(r"process\.env\.([A-Z][A-Z0-9_]+)"),
    re.compile(r"process\.env\[\s*['\"]([A-Z][A-Z0-9_]+)['\"]\s*\]"),
    re.compile(r"import\.meta\.env\.([A-Z][A-Z0-9_]+)"),
    re.compile(r"os\.environ(?:\.get)?\s*[\[(]\s*['\"]([A-Z][A-Z0-9_]+)['\"]"),
    re.compile(r"os\.getenv\s*\(\s*['\"]([A-Z][A-Z0-9_]+)['\"]"),
    re.compile(r"Environment\.GetEnvironmentVariable\s*\(\s*\"([A-Z][A-Z0-9_]+)\""),
    re.compile(r"System\.getenv\s*\(\s*\"([A-Z][A-Z0-9_]+)\""),
    re.compile(r"os\.(?:Getenv|LookupEnv)\s*\(\s*\"([A-Z][A-Z0-9_]+)\""),
    re.compile(r"env::var\s*\(\s*\"([A-Z][A-Z0-9_]+)\""),
]
# Defaults of these are never written to the report (it is meant to be committed and shared).
SECRET_NAME = re.compile(r"PASS|PWD|SECRET|TOKEN|KEY|CREDENTIAL|PRIVATE|AUTH|CONN|DSN|SALT|CERT", re.IGNORECASE)


def _safe_default(name, value):
    if value in (None, "") or SECRET_NAME.search(name):
        return None
    return value


PLACEHOLDER = re.compile(r"\$\{([A-Z][A-Z0-9_]+)(?::-?([^}]*))?\}")
CONFIG_FILE = re.compile(r"^(application|bootstrap)[\w-]*\.(ya?ml|properties)$|^appsettings[\w.]*\.json$|^\.env(\.[\w-]+)?$|^config\.(ya?ml|json|toml)$|^settings\.(ya?ml|toml)$")


def configuration(repo, files, owner_of, services, index=None):
    """{variables: [{name, default, sources: [file:line], containers}], files: [config files]}"""
    variables = {}

    def add(name, file, line, default=None, container=None):
        default = _safe_default(name, default)
        entry = variables.setdefault(name, {"name": name, "default": None, "sources": [], "containers": set()})
        if default not in (None, "") and entry["default"] is None:
            entry["default"] = default
        source = f"{file}:{line}"
        if len(entry["sources"]) < 3 and not any(s.split(":")[0] == file for s in entry["sources"]):
            entry["sources"].append(source)
        if container:
            entry["containers"].add(container)

    for file in files:
        text = _file_text(file)
        for pattern in ENV_PATTERNS:
            for m in pattern.finditer(text):
                add(m.group(1), _rel(repo, file), _line_of(text, m.start()), container=owner_of(file))

    config_files = []
    if index is not None:
        config_candidates = index.walk(lambda name: CONFIG_FILE.match(name) is not None)
    else:
        config_candidates = walk_files(repo, lambda name: CONFIG_FILE.match(name) is not None)
    for file in config_candidates:
        if _is_test(file, repo):
            continue
        relative = _rel(repo, file)
        config_files.append(relative)
        text = _file_text(file)
        container = owner_of(file.resolve())
        if file.name.startswith(".env"):
            for m in re.finditer(r"^\s*([A-Z][A-Z0-9_]+)\s*=\s*(.*)$", text, re.MULTILINE):
                # Names only: values in .env files are local settings or secrets.
                add(m.group(1), relative, _line_of(text, m.start()), None, container)
            continue
        for m in PLACEHOLDER.finditer(text):
            add(m.group(1), relative, _line_of(text, m.start()), m.group(2), container)

    for service in services:
        for name, value in service["environment"].items():
            if re.match(r"^[A-Z][A-Z0-9_]*$", name):
                add(name, service["file"], service["line"], value or None, None)

    return {
        "variables": [
            {**v, "containers": sorted(v["containers"])} for v in sorted(variables.values(), key=lambda v: v["name"])
        ],
        "files": sorted(config_files),
    }


# ---------- technology inventory ----------

KEY_LIBRARIES = {
    "spring-boot", "spring-boot-starter-web", "spring-boot-starter-webflux", "spring-boot-starter-data-jpa",
    "spring-boot-starter-data-redis", "spring-boot-starter-security", "spring-boot-starter-actuator",
    "hibernate-core", "flyway-core", "liquibase-core", "lombok", "mapstruct", "springdoc-openapi-starter-webmvc-ui",
    "micrometer-registry-prometheus", "resilience4j-spring-boot3", "bucket4j-core", "quarkus-core", "micronaut-core",
}


def _maven_inventory(pom_text):
    items = []
    parent = re.search(r"<parent>.*?<artifactId>([^<]+)</artifactId>\s*<version>([^<]+)</version>", pom_text, re.DOTALL)
    if parent and "spring-boot" in parent.group(1):
        items.append(f"Spring Boot {parent.group(2)}")
    java = re.search(r"<(?:java\.version|maven\.compiler\.release|maven\.compiler\.target)>([^<]+)<", pom_text)
    if java:
        items.append(f"Java {java.group(1)}")
    for block in re.findall(r"<dependency>(.*?)</dependency>", pom_text, re.DOTALL):
        artifact = re.search(r"<artifactId>([^<]+)</artifactId>", block)
        if not artifact or re.search(r"<scope>\s*test\s*</scope>", block):
            continue
        version = re.search(r"<version>([^<$]+)</version>", block)
        name = artifact.group(1)
        if name in KEY_LIBRARIES or name.startswith("spring-boot-starter-"):
            items.append(name + (f" {version.group(1)}" if version else ""))
    return items


def inventory(repo, container, module_paths, index=None):
    """Runtime, frameworks and key libraries (with versions when declared) for one container."""
    items = []
    base = (repo / container["path"]).resolve() if container.get("path") else None
    manifests = []
    for path in module_paths:
        if path.is_file():
            manifests.append(path)
    if base and base.is_dir():
        for name in ("package.json", "pyproject.toml", "requirements.txt", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts", "Cargo.toml"):
            if (base / name).is_file():
                manifests.append(base / name)
        # Maven parent POM one level up (multi-module builds declare versions there).
        if (base.parent / "pom.xml").is_file() and (base / "pom.xml").is_file():
            manifests.append(base.parent / "pom.xml")

    for manifest in dict.fromkeys(manifests):
        name = manifest.name
        if name == "package.json":
            data = index.read_json(manifest) if index is not None else None
            if data is None:
                try:
                    data = json.loads(_file_text(manifest))
                except ValueError:
                    continue
            for field in ("dependencies", "devDependencies"):
                for dep, version in (data.get(field) or {}).items():
                    if field == "dependencies" or dep in ("typescript", "vite", "webpack", "jest", "vitest", "eslint", "tailwindcss", "@playwright/test"):
                        items.append(f"{dep} {version}")
            engines = (data.get("engines") or {}).get("node")
            if engines:
                items.insert(0, f"Node.js {engines}")
        elif name == "pom.xml":
            text = _file_text(manifest)
            items += _maven_inventory(text)
        elif name.startswith("build.gradle"):
            text = _file_text(manifest)
            for m in re.finditer(r"""(?:implementation|api|runtimeOnly)\s*\(?\s*['"]([\w.-]+):([\w.-]+)(?::([\w.-]+))?['"]""", text):
                items.append(m.group(2) + (f" {m.group(3)}" if m.group(3) else ""))
            plugin = re.search(r"""org\.springframework\.boot['"]\)?\s*version\s*['"]([^'"]+)""", text)
            if plugin:
                items.insert(0, f"Spring Boot {plugin.group(1)}")
        elif name.endswith("proj"):
            text = _file_text(manifest)
            try:
                root = ET.fromstring(text.encode("utf-8"))
            except ET.ParseError:
                continue
            for e in root.iter():
                tag = local_tag(e)
                if tag in ("TargetFramework", "TargetFrameworks") and e.text:
                    items.insert(0, e.text.strip())
                elif tag == "PackageReference" and e.attrib.get("Include"):
                    items.append(e.attrib["Include"] + (f" {e.attrib['Version']}" if e.attrib.get("Version") else ""))
        elif name == "pyproject.toml":
            text = _file_text(manifest)
            python = re.search(r"requires-python\s*=\s*['\"]([^'\"]+)", text)
            if python:
                items.insert(0, f"Python {python.group(1)}")
            block = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.MULTILINE | re.DOTALL)
            if block:
                items += [d.strip() for d in re.findall(r"['\"]([^'\"]+)['\"]", block.group(1))]
        elif name == "requirements.txt":
            text = _file_text(manifest)
            items += [l.strip() for l in text.splitlines() if l.strip() and not l.startswith(("#", "-"))]
        elif name == "go.mod":
            text = _file_text(manifest)
            go = re.search(r"^go\s+(\S+)", text, re.MULTILINE)
            if go:
                items.insert(0, f"Go {go.group(1)}")
            items += [f"{m.group(1)} {m.group(2)}" for m in re.finditer(r"^\s*([\w.\-/]+)\s+(v[\w.\-+]+)(?!\s*//\s*indirect)\s*$", text, re.MULTILINE)]
    items = list(dict.fromkeys(items))
    platform = [i for i in items if re.match(r"^(Spring Boot|Java|Go|Python|Node\.js|net\d|netcoreapp|netstandard)", i)]
    return (platform + [i for i in items if i not in platform])[:25]


# ---------- dev-server proxies (front end -> back end) ----------

DEV_PROXY = [
    # vite / webpack-dev-server: '/api': { target: 'http://localhost:8080' } or '/api': 'http://localhost:8080'
    re.compile(r"""['"](/[\w/-]*)['"]\s*:\s*(?:\{[^}]*?target\s*:\s*)?['"](https?://[^'"]+)['"]""", re.DOTALL),
    # next.config rewrites: source: '/api/:path*', destination: 'http://localhost:8080/...'
    re.compile(r"""source\s*:\s*['"](/[^'"]*)['"]\s*,\s*destination\s*:\s*['"](https?://[^'"]+)['"]"""),
]


def dev_proxies(repo, index=None):
    """[(prefix, target url, file, line)] from front-end dev-server configs and package.json "proxy"."""
    found = []
    if index is not None:
        config_candidates = index.walk(lambda n: re.match(r"(vite|webpack|next|vue|angular)\.config\.\w+$|^proxy\.conf\.json$|^setupProxy\.js$", n))
        pkg_candidates = index.walk(lambda n: n == "package.json")
    else:
        config_candidates = walk_files(repo, lambda n: re.match(r"(vite|webpack|next|vue|angular)\.config\.\w+$|^proxy\.conf\.json$|^setupProxy\.js$", n))
        pkg_candidates = walk_files(repo, lambda n: n == "package.json")
    for file in config_candidates:
        text = _file_text(file)
        if "proxy" not in text and "rewrites" not in text:
            continue
        for pattern in DEV_PROXY:
            for m in pattern.finditer(text):
                if "localhost" in m.group(2) or "127.0.0.1" in m.group(2) or re.search(r"://[\w-]+:\d+", m.group(2)):
                    found.append((m.group(1), m.group(2), file.resolve(), _line_of(text, m.start())))
    for file in pkg_candidates:
        if index is not None:
            data = index.read_json(file)
            text = json.dumps(data) if data else ""
        else:
            text = _file_text(file)
        m = re.search(r'"proxy"\s*:\s*"(https?://[^"]+)"', text)
        if m:
            found.append(("/", m.group(1), file.resolve(), _line_of(text, m.start())))
    return found


def declared_ports(repo, container_dir):
    """Ports a back end listens on, from its own config (server.port, PORT, launchSettings, listen calls)."""
    ports = set()
    for file in walk_files(container_dir, lambda n: re.match(r"application[\w-]*\.(ya?ml|properties)$|launchSettings\.json$|^\.env|\.(js|ts|py|go)$", n) is not None):
        if _is_test(file, container_dir):
            continue
        text = _file_text(file)
        for m in re.finditer(r"port\s*[:=]\s*\$\{[A-Z_]+:(\d{2,5})\}|server\.port\s*[:=]\s*(\d{2,5})|^\s*port\s*:\s*(\d{2,5})\s*$|PORT\s*(?:=|\|\||\?\?|or)\s*['\"]?(\d{2,5})|localhost:(\d{2,5})|listen\(\s*(\d{2,5})|:(\d{2,5})\"\s*\)", text, re.MULTILINE):
            ports.add(next(g for g in m.groups() if g))
    return ports
