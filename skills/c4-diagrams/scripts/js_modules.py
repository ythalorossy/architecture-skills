"""Folder-level import graph for a single JavaScript/TypeScript package."""

import json
import re
from pathlib import Path

try:
    from scripts.repo_index import is_ignored_dir, read_file_text, walk_files
    from scripts.paths import project_group
except ImportError:
    from repo_index import is_ignored_dir, read_file_text, walk_files
    from paths import project_group


SOURCE_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".vue", ".svelte")

# Folders of static or vendored files, not application code.
NON_CODE_DIRS = {"assets", "public", "static", "vendor", "wwwroot"}

IMPORT = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*\(?\s*|\brequire\s*\(\s*)['"]([^'"\n]+)['"]"""
)

# A folder holding at least this share of the code is drawn one level deeper.
DOMINANT_SHARE = 0.8


def _is_source(name):
    return name.endswith(SOURCE_EXTENSIONS) and not name.endswith((".min.js", ".d.ts"))


def _source_files(directory, index=None):
    """Source files under a directory, served from the run's index when there is one."""
    if index is not None:
        return list(index.walk(_is_source, under=directory))
    return list(walk_files(directory, _is_source))


def _code_dirs(directory, index=None):
    return sorted(
        child for child in directory.iterdir()
        if child.is_dir()
        and not is_ignored_dir(child.name)
        and child.name not in NON_CODE_DIRS
        and _source_files(child, index)
    )


def _strip_jsonc(text):
    """Drop // and /* */ comments and trailing commas, leaving strings alone."""
    out = []
    i = 0
    while i < len(text):
        char = text[i]
        if char == '"':
            end = i + 1
            while end < len(text) and text[end] != '"':
                end += 2 if text[end] == "\\" else 1
            out.append(text[i:end + 1])
            i = end + 1
        elif text.startswith("//", i):
            i = text.find("\n", i) if "\n" in text[i:] else len(text)
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = len(text) if end < 0 else end + 2
        else:
            out.append(char)
            i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def _compiler_options(config, depth=0):
    """compilerOptions of a tsconfig/jsconfig, following relative "extends"."""
    try:
        data = json.loads(_strip_jsonc(config.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError):
        return {}, config.parent

    options, base = {}, config.parent
    extends = data.get("extends")
    if isinstance(extends, str) and extends.startswith(".") and depth < 5:
        parent = (config.parent / extends).resolve()
        parent = parent if parent.suffix == ".json" else parent.with_suffix(".json")
        if parent.exists():
            options, base = _compiler_options(parent, depth + 1)

    own = data.get("compilerOptions", {})
    if "baseUrl" in own or "paths" in own:
        base = config.parent
    return {**options, **own}, base


def _resolvers(package_dir):
    """Return (baseUrl directory or None, [(alias prefix, alias suffix, [target dirs])])."""
    for name in ("tsconfig.json", "jsconfig.json"):
        config = package_dir / name
        if config.exists():
            options, base = _compiler_options(config)
            break
    else:
        return None, []

    base_url = (base / options["baseUrl"]).resolve() if "baseUrl" in options else None
    paths_base = base_url or base

    aliases = []
    for pattern, targets in (options.get("paths") or {}).items():
        prefix, _, suffix = pattern.partition("*")
        aliases.append((prefix, suffix, [paths_base / t.replace("*", "{}") for t in targets]))

    return base_url, aliases


def _exists(path):
    if path.exists():
        return True
    if any(path.with_name(path.name + ext).exists() for ext in SOURCE_EXTENSIONS):
        return True
    return path.is_dir()


def _resolve(spec, file, base_url, aliases):
    if spec.startswith("."):
        return (file.parent / spec).resolve()

    for prefix, suffix, targets in aliases:
        if spec.startswith(prefix) and spec.endswith(suffix) and len(spec) >= len(prefix + suffix):
            middle = spec[len(prefix):len(spec) - len(suffix)] if suffix else spec[len(prefix):]
            for target in targets:
                candidate = Path(str(target).format(middle)).resolve()
                if _exists(candidate):
                    return candidate

    if base_url:
        candidate = (base_url / spec).resolve()
        if _exists(candidate):
            return candidate

    return None  # third-party package


def _nodes(package_dir, index=None):
    """
    Map node directory -> whether it owns its whole subtree.

    Start at src/ (or the package folder) and keep descending into a child
    folder while it holds most of the code. Every folder on that path keeps its
    loose files as one node; the other code folders met on the way are nodes.
    """
    current = package_dir / "src" if (package_dir / "src").is_dir() else package_dir
    nodes = {}

    while True:
        children = _code_dirs(current, index)
        if any(_is_source(f.name) for f in current.iterdir() if f.is_file()):
            nodes[current] = False

        total = len(_source_files(current, index))
        dominant = [c for c in children if total and len(_source_files(c, index)) / total >= DOMINANT_SHARE]

        for child in children:
            if child not in dominant:
                nodes[child] = True

        if not dominant:
            return nodes
        current = dominant[0]


def module_projects(repo, package_dir, ecosystem="Node.js", index=None):
    package_dir = package_dir.resolve()
    nodes = _nodes(package_dir, index)
    if len(nodes) < 2:
        return []

    base_url, aliases = _resolvers(package_dir)

    def owner(path):
        for candidate in [path, *path.parents]:
            if nodes.get(candidate) is True:
                return candidate
            if candidate == package_dir:
                break
        return path.parent if nodes.get(path.parent) is False else None

    projects = []
    for directory, whole_subtree in nodes.items():
        files = (
            _source_files(directory, index) if whole_subtree
            else [f for f in sorted(directory.iterdir()) if f.is_file() and _is_source(f.name)]
        )

        targets = []
        for file in files:
            text = index.read_text(file) if index is not None else None
            if text is None:
                text = read_file_text(file, "js_modules")
            for spec in IMPORT.findall(text):
                resolved = _resolve(spec, file, base_url, aliases)
                target = owner(resolved) if resolved else None
                if target and target != directory and target not in targets:
                    targets.append(target)

        relative = directory.relative_to(repo).as_posix()
        projects.append({
            "name": (relative if relative != "." else package_dir.name) + ("" if whole_subtree else " (files)"),
            "path": directory,
            "relative_path": relative,
            "group": project_group(relative),
            "ecosystem": ecosystem,
            "in_solution": None,
            "references": sorted(targets),
        })

    return projects
