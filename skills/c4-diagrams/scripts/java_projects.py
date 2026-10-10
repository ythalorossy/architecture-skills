import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from scripts.repo_index import walk_files
    from scripts.paths import local_tag, project_group
except ImportError:
    from repo_index import walk_files
    from paths import local_tag, project_group


GRADLE_SETTINGS = ("settings.gradle", "settings.gradle.kts")
GRADLE_BUILD = ("build.gradle", "build.gradle.kts")

QUOTED = re.compile(r"""["']([^"']+)["']""")
INCLUDE_CALL = re.compile(r"\binclude\s*\(([^)]*)\)", re.DOTALL)
INCLUDE_BARE = re.compile(r"^\s*include\s+([^(\n][^\n]*)$", re.MULTILINE)
ROOT_NAME = re.compile(r"""rootProject\.name\s*=\s*["']([^"']+)["']""")
PROJECT_DIR = re.compile(
    r"""project\(\s*["'](:?[^"']+)["']\s*\)\.projectDir\s*=\s*(?:file|File)\(\s*["']([^"']+)["']\s*\)"""
)
PROJECT_REF = re.compile(r"""\bproject\(\s*(?:path\s*[:=]\s*)?["'](:[^"']*)["']""")
ACCESSOR_REF = re.compile(r"\bprojects\.([A-Za-z_][\w.]*)")


# ---------- Maven ----------

def _children(element, tag):
    return [child for child in element if local_tag(child) == tag]


def _text(element, tag):
    found = _children(element, tag) if element is not None else []
    return found[0].text.strip() if found and found[0].text else None


def _parse_pom(file, collector=None):
    try:
        root = ET.parse(file).getroot()
    except ET.ParseError as ex:
        if collector:
            collector.parse_error("java_projects", str(file), f"invalid XML: {ex}")
        return None

    modules = []
    for container in [root] + [p for ps in _children(root, "profiles") for p in _children(ps, "profile")]:
        for group in _children(container, "modules"):
            for module in _children(group, "module"):
                target = (file.parent / module.text.strip()).resolve()
                modules.append(target if target.suffix == ".xml" else target / "pom.xml")

    dependencies = [
        _text(dependency, "artifactId")
        for group in _children(root, "dependencies")
        for dependency in _children(group, "dependency")
    ]

    return {
        "artifact": _text(root, "artifactId") or file.parent.name,
        "packaging": _text(root, "packaging") or "jar",
        "modules": modules,
        "dependencies": [d for d in dependencies if d],
    }


def _maven(repo, index=None, collector=None):
    poms = {}
    if index is not None:
        candidates = index.walk(lambda name: name == "pom.xml")
    else:
        candidates = walk_files(repo, lambda name: name == "pom.xml")
    for file in candidates:
        pom = _parse_pom(file, collector)
        if pom:
            poms[file.resolve()] = pom

    listed = {module for pom in poms.values() for module in pom["modules"]}
    aggregators = [path for path, pom in poms.items() if pom["modules"] and path not in listed]

    # Parent/aggregator POMs hold no code, so only real modules become nodes.
    modules = {path: pom for path, pom in poms.items() if pom["packaging"] != "pom"}
    by_artifact = {pom["artifact"]: path for path, pom in modules.items()}

    projects = []
    for path, pom in modules.items():
        relative = path.relative_to(repo).as_posix()
        projects.append({
            "name": pom["artifact"],
            "path": path,
            "relative_path": relative,
            "group": project_group(relative),
            "ecosystem": "Java (Maven)",
            "in_solution": (path in listed) if aggregators else None,
            "references": sorted({
                by_artifact[artifact]
                for artifact in pom["dependencies"]
                if artifact in by_artifact and by_artifact[artifact] != path
            }),
        })

    return [p.relative_to(repo).as_posix() for p in aggregators], projects


# ---------- Gradle ----------

def _accessor_key(gradle_path):
    """Key that type-safe accessors (projects.fooBar.baz) and :foo-bar:baz share."""
    return ".".join(
        re.sub(r"[-_]", "", segment).lower()
        for segment in gradle_path.strip(":").split(":")
    )


def _build_file(directory):
    for name in GRADLE_BUILD:
        if (directory / name).exists():
            return directory / name
    return None


def _gradle_build(repo, settings, collector=None):
    text = settings.read_text(encoding="utf-8", errors="replace")
    base = settings.parent

    included = []
    for match in INCLUDE_CALL.findall(text) + INCLUDE_BARE.findall(text):
        included += QUOTED.findall(match)

    overrides = {
        ":" + path.lstrip(":"): (base / directory).resolve()
        for path, directory in PROJECT_DIR.findall(text)
    }

    gradle_projects = {}
    for include in included:
        path = ":" + include.lstrip(":")
        gradle_projects[path] = overrides.get(path, (base / path.strip(":").replace(":", "/")).resolve())

    root_name = ROOT_NAME.search(text)
    if _build_file(base) and (base / "src").is_dir():
        gradle_projects[":"] = base.resolve()

    keys = {_accessor_key(path): path for path in gradle_projects}

    projects = []
    for path, directory in gradle_projects.items():
        build_file = _build_file(directory)
        node_path = (build_file or directory).resolve()
        references = []

        if build_file:
            build_text = build_file.read_text(encoding="utf-8", errors="replace")
            targets = PROJECT_REF.findall(build_text)
            targets += [keys.get(a.lower(), ":" + a.replace(".", ":")) for a in ACCESSOR_REF.findall(build_text)]

            for target in targets:
                target = ":" + target.lstrip(":") if target != ":" else target
                if target == path:
                    continue
                if target in gradle_projects:
                    resolved = (_build_file(gradle_projects[target]) or gradle_projects[target]).resolve()
                else:
                    resolved = target.strip(":")  # not included in settings: unresolved
                if resolved not in references:
                    references.append(resolved)

        relative = node_path.relative_to(repo).as_posix()
        projects.append({
            "name": (root_name.group(1) if root_name else base.name) if path == ":" else path.strip(":"),
            "path": node_path,
            "relative_path": relative,
            "group": project_group(relative),
            "ecosystem": "Java (Gradle)",
            "in_solution": None,
            "references": references,
        })

    return projects


def _gradle(repo, index=None, collector=None):
    if index is not None:
        settings_files = list(index.walk(lambda name: name in GRADLE_SETTINGS))
    else:
        settings_files = list(walk_files(repo, lambda name: name in GRADLE_SETTINGS))
    projects = []
    for settings in settings_files:
        projects += _gradle_build(repo, settings, collector)
    return [s.relative_to(repo).as_posix() for s in settings_files], projects


def discover_projects(repo_path, index=None, collector=None):
    """
    Maven modules (artifactId) and Gradle subprojects (settings includes).

    Maven edges are <dependency> artifactIds naming another module; when an
    aggregator POM exists, modules it does not list get in_solution=False.
    Gradle edges are project(':x') and projects.x references in build files.

    The `index` parameter is accepted for API compatibility but not yet used.
    Pass a DiagnosticsCollector to route warnings through the diagnostics channel.
    """
    repo = Path(repo_path).resolve()

    maven_roots, maven_projects = _maven(repo, index, collector)
    gradle_roots, gradle_projects = _gradle(repo, index, collector)

    return {
        "solutions": maven_roots + gradle_roots,
        "projects": maven_projects + gradle_projects,
    }
