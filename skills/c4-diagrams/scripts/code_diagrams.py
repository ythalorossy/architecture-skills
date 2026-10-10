"""
C4 Level 4 (code): the components the agent lists in c4-model.json `code` are
resolved to their source files, their types extracted (code_types.py) and drawn
as Mermaid class diagrams.
"""
from difflib import get_close_matches
from pathlib import Path
import os
import re

try:
    from scripts import code_facts, code_types
    from scripts.c4_facts import slug, _is_vendored
    from scripts.repo_index import walk_files
except ImportError:
    import code_facts, code_types
    from c4_facts import slug, _is_vendored
    from repo_index import walk_files

MAX_TYPES = 12
MAX_MEMBERS = 8
KEY_COMPONENTS = 5


def repository_root(repo, output):
    """The repository as seen from the output folder (forward slashes); absolute when there is no relative path."""
    repo = Path(repo).resolve()
    try:
        return Path(os.path.relpath(repo, Path(output).resolve())).as_posix()
    except ValueError:  # another drive on Windows
        return repo.as_posix()


def _module_dirs(repo, container_fact):
    dirs = {}
    for module, info in ((container_fact.get("components") or {}).get("nodes") or {}).items():
        path = repo / info["path"]
        dirs[module] = (path.parent if path.is_file() else path).resolve()
    if not dirs and container_fact.get("path"):
        dirs[container_fact["name"]] = (repo / container_fact["path"]).resolve()
    return dirs


def _skipped(file, base):
    try:
        Path(file).relative_to(base)
    except ValueError:  # a symlink to a file outside the folder
        return True
    return (
        code_facts._is_test(file, base)
        or _is_vendored(Path(file).relative_to(base).parts)
        or code_types.is_generated(Path(file).name)
    )


def component_files(repo, container_fact, component):
    """Source files of a module or a code component (`module::package`): tests, vendored and generated files left out."""
    repo = Path(repo).resolve()
    dirs = _module_dirs(repo, container_fact)
    if component in dirs:
        folder = dirs[component]
        files = walk_files(folder, lambda name: Path(name).suffix.lower() in code_types.LANGUAGES)
        return sorted(f.resolve() for f in files if not _skipped(f.resolve(), folder))
    owners = (code_facts.code_components(dirs) or {}).get("_files", {})
    return sorted(f for f, node in owners.items() if node == component and not _skipped(f, repo))


def _component_ids(container_fact):
    ids = set((container_fact.get("components") or {}).get("nodes") or {})
    ids |= set((container_fact.get("code_components") or {}).get("nodes") or {})
    if not ids and container_fact.get("path"):
        ids.add(container_fact["name"])
    return ids


def _suggest(name, options):
    matches = get_close_matches(name, sorted(options), n=3, cutoff=0.5)
    return f" (did you mean {', '.join(matches)}?)" if matches else ""


def _neighbors(types):
    near = {name: set() for name in types}
    for name, t in types.items():
        for other in t["bases"] + t["interfaces"] + t["embeds"] + t["depends_on"]:
            if other in types and other != name:
                near[name].add(other)
                near[other].add(name)
    return near


def select_types(types, wanted=(), limit=MAX_TYPES):
    """(chosen, left out): the wanted types and their neighbours, or the most connected types."""
    near = _neighbors(types)
    rank = sorted(types, key=lambda n: (-len(near[n]), -len(types[n]["methods"]), n))
    if wanted:
        chosen = list(dict.fromkeys(wanted))[:limit]
        for name in rank:
            if len(chosen) >= limit:
                break
            if name not in chosen and any(name in near[w] for w in wanted):
                chosen.append(name)
    else:
        chosen = rank[:limit]
    return chosen, sorted(set(types) - set(chosen))


# One `style` line per box: mermaid-cli accepts classDef/cssClass in class diagrams but emits no CSS for them.
COMPONENT_STYLE = "fill:#85bbf0,stroke:#5d82a8,color:#000000"
SHARED_STYLE = "fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3"
SAFE_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Words the classDiagram grammar reads as statements (checked case-insensitively).
MERMAID_WORDS = {"class", "classdef", "cssclass", "classdiagram", "note", "link", "click", "callback", "call",
                 "style", "namespace", "direction", "href", "end", "graph"}
STEREOTYPES = {"interface", "abstract", "enum", "record", "struct"}


def _member(method):
    """"Load(id) Task<List<Job>>" -> "+Load(id) Task#lt;List#lt;Job#gt;#gt;" (entity codes: Mermaid's ~T~ generics
    garble nested types with commas; no parens or braces in the type)."""
    head, _, ret = method.partition(")")
    ret = re.sub(r"[(){}]", "", ret).strip().replace("<", "#lt;").replace(">", "#gt;").rstrip("*$")
    return f"+{head})" + (f" {ret}" if ret else "")


def _ids(names):
    """Mermaid id per name: the name itself when safe, else a generated id drawn with the name as its label."""
    ids, used = {}, set(names)
    for name in names:
        if SAFE_ID.fullmatch(name) and name.lower() not in MERMAID_WORDS:
            ids[name] = name
            continue
        number = len(ids)
        while f"T{number}" in used:
            number += 1
        ids[name] = f"T{number}"
        used.add(ids[name])
    return ids


def _box(t, ref):
    members = list(t["values"]) if t["kind"] == "enum" else [_member(m) for m in t["methods"]]
    extra = len(members) - MAX_MEMBERS
    # Mermaid puts a line with parentheses in the methods compartment and one without among the attributes.
    more = f"… {extra} more" if t["kind"] == "enum" else f"…({extra} more)"
    members = members[:MAX_MEMBERS] + ([more] if extra > 0 else [])
    head = [f"<<{t['kind']}>>"] if t["kind"] in STEREOTYPES else []
    if not head and not members:
        return [f"    class {ref}"]
    return [f"    class {ref} {{"] + [f"        {line}" for line in head + members] + ["    }"]


def _groups(types, chosen, external):
    """Number of unconnected groups among the drawn boxes."""
    owner = {name: name for name in list(chosen) + list(external)}

    def find(name):
        while owner[name] != name:
            name = owner[name]
        return name

    for name in chosen:
        t = types[name]
        for other in t["bases"] + t["interfaces"] + t["embeds"] + t["depends_on"]:
            if other in owner:
                owner[find(other)] = find(name)
    return len({find(name) for name in owner})


def class_diagram(types, chosen):
    """Mermaid classDiagram of the chosen types; base types from other components are drawn as external boxes."""
    external = []
    for name in chosen:
        t = types[name]
        for parent in t["bases"] + t["interfaces"] + t["embeds"]:
            if parent not in types and parent not in external:
                external.append(parent)
    # Unconnected groups sit side by side across the layout direction: with several, stack them (LR) so the
    # diagram stays narrow enough to read.
    direction = "LR" if _groups(types, chosen, external) >= 3 else "TB"
    lines = ["---", "config:", "  class:", "    hideEmptyMembersBox: true", "---", "classDiagram", f"    direction {direction}"]
    ids = _ids(list(chosen) + external)
    ref = {name: ids[name] if ids[name] == name else f'{ids[name]}["{name}"]' for name in ids}
    for name in chosen:
        lines += _box(types[name], ref[name])
    for name in external:
        lines += [f"    class {ref[name]} {{", "        <<external>>", "    }"]
    for name in chosen:
        t, me = types[name], ids[name]
        lines += [f"    {ids[b]} <|-- {me}" for b in t["bases"] if b in ids]
        lines += [f"    {ids[i]} <|.. {me}" for i in t["interfaces"] if i in ids]
        lines += [f"    {me} *-- {ids[e]}" for e in t["embeds"] if e in ids]
        lines += [f"    {me} ..> {ids[d]}" for d in t["depends_on"] if d in chosen]
    lines += [f"    style {ids[name]} {COMPONENT_STYLE}" for name in chosen]
    lines += [f"    style {ids[name]} {SHARED_STYLE}" for name in external]
    return "\n".join(lines) + "\n"


def _relative(file, repo):
    try:
        return Path(file).relative_to(repo).as_posix()
    except ValueError:
        return Path(file).as_posix()


def notes(entry):
    """Report lines under a Level 4 diagram: where each drawn type is declared, and what was left out."""
    sources = ", ".join(
        f"{name} → `{_relative(entry['types'][name]['file'], entry['repo'])}:{entry['types'][name]['line']}`"
        for name in entry["chosen"]
    )
    lines = [f"Sources: {sources}"]
    left_out = entry["left_out"]
    if left_out:
        shown = ", ".join(left_out[:10]) + (", …" if len(left_out) > 10 else "")
        lines.append(f"Not drawn: {len(left_out)} more type{'s' if len(left_out) > 1 else ''} ({shown})")
    return lines


def prepare(model, facts, output, collector=None, repo_override=None):
    """(errors, warnings, entries) for model["code"]; every entry is ready to draw."""
    code = model.get("code") or []
    if not isinstance(code, list):
        return ["code: must be a list of {container, component, description, types}"], [], []
    if not code:
        return [], [], []
    errors, warnings, entries, stems = [], [], [], set()
    if len(code) > KEY_COMPONENTS:
        warnings.append(
            f"code: {len(code)} components; Level 4 is meant for the {KEY_COMPONENTS} or fewer that matter most"
        )
    if "repository_root" not in facts and repo_override is None:
        return ["code: c4-facts.json has no repository_root; re-run analyze_repository.py"], warnings, []
    repo_rel = repo_override if repo_override else facts.get("repository_root", "")
    repo = (Path(output) / repo_rel).resolve() if repo_override else (Path(output) / facts["repository_root"]).resolve()
    # Relocatable output (ARC-06): verify the resolved path points to a directory
    # whose name matches the last segment of the relative path.  If not, skip
    # Level 4 with a model-tier warning.
    if not repo.is_dir() or (not repo_override and repo.name != Path(repo_rel).name):
        msg = (
            f"repository not found at {repo_rel}; re-run analyze_repository.py "
            f"or pass --repo <path> to render_c4.py"
        )
        if collector is not None:
            collector.model_warning("code_diagrams", msg)
        else:
            warnings.append(msg)
        return [], warnings, []
    elements = {c["id"]: c for c in model.get("containers") or []}

    for number, item in enumerate(code, 1):
        where = f"code[{number}]"
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) and item[k] for k in ("container", "component")):
            errors.append(f"{where}: needs a container and a component")
            continue
        wanted = item.get("types") or []
        if not isinstance(wanted, list) or not all(isinstance(name, str) for name in wanted):
            errors.append(f"{where}: types must be a list of type names")
            continue
        element = elements.get(item["container"])
        covers = (element.get("facts") or [element["id"]]) if element else []
        candidates = [c for c in facts["containers"] if c["id"] in covers]
        if not candidates:
            errors.append(f"{where}: {item['container']!r} is not a container in the model")
            continue
        fact = next((c for c in candidates if item["component"] in _component_ids(c)), None)
        if fact is None:
            ids = set().union(*(_component_ids(c) for c in candidates))
            errors.append(f"{where}: {item['component']!r} is not a component of {item['container']}{_suggest(item['component'], ids)}")
            continue
        stem = f"c4-code-{item['container']}-{slug(item['component'])}"
        if stem in stems:
            errors.append(f"{where}: {item['component']} is listed twice")
            continue
        stems.add(stem)
        types = code_types.extract(component_files(repo, fact, item["component"]))
        if not types:
            warnings.append(f"{where}: no classes or interfaces found in {item['component']}; no Level 4 diagram for it")
            continue
        unknown = [name for name in wanted if name not in types]
        if unknown:
            errors += [f"{where}: type {name!r} not found in {item['component']}{_suggest(name, types)}" for name in unknown]
            continue
        chosen, left_out = select_types(types, wanted)
        entries.append({
            "stem": stem,
            "title": f"{element['name']} · {item['component']}",
            "description": item.get("description", ""),
            "types": types, "chosen": chosen, "left_out": left_out, "repo": repo,
            "mermaid": class_diagram(types, chosen),
        })
    return errors, warnings, entries
