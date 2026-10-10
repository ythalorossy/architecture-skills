"""
Types (classes, interfaces, enums, records, structs) and their public methods,
read from source with regexes, for the C4 Level 4 (code) diagrams. No compiler
or toolchain is needed; like the rest of the skill it is a best-effort reading
of the code.

    extract(files) -> {type name: {name, kind, language, file, line, bases,
                       interfaces, methods, values, depends_on, embeds}}
"""
from pathlib import Path
import re

LANGUAGES = {
    ".cs": "cs", ".java": "java", ".kt": "kotlin", ".go": "go", ".py": "python",
    ".ts": "ts", ".tsx": "ts", ".js": "ts", ".jsx": "ts", ".mjs": "ts",
}
GENERATED = re.compile(
    r"(\.designer\.cs|\.g\.cs|\.g\.i\.cs|^reference\.cs|_pb2\.py|\.generated\.\w+|\.d\.ts|\.min\.m?js)$",
    re.IGNORECASE,
)
QUOTES = {"cs": "\"'", "java": "\"'", "kotlin": "\"'", "go": "\"'`", "python": "\"'", "ts": "\"'`"}
TRIPLE = {"cs": ('"""',), "java": ('"""',), "kotlin": ('"""',), "python": ('"""', "'''")}
# Words a member regex can mistake for a return type.
NOT_TYPES = {
    "return", "new", "await", "throw", "else", "delegate", "event", "operator", "implicit", "explicit",
    "using", "yield", "public", "private", "protected", "internal", "static", "var", "case", "goto",
}
NO_BODY = re.compile(r";|\b(?:class|interface|object|enum|record|struct|fun|func|def|type)\b")


def is_generated(name):
    return GENERATED.search(name) is not None


def _load_source(path):
    try:
        return Path(path).read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")
    except OSError:
        return ""


def _line_of(text, index):
    return text.count("\n", 0, index) + 1


def _mask(text, language):
    """The text with comments and string contents blanked (newlines kept), so offsets still match."""
    out = list(text)
    n = len(text)
    comment = "#" if language == "python" else "//"

    def blank(start, end):
        for k in range(start, min(end, n)):
            if out[k] != "\n":
                out[k] = " "

    i = 0
    while i < n:
        triple = next((q for q in TRIPLE.get(language, ()) if text.startswith(q, i)), None)
        if text.startswith(comment, i):
            end = text.find("\n", i)
            end = n if end < 0 else end
            blank(i, end)
            i = end
        elif language != "python" and text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            blank(i, end)
            i = end
        elif triple:
            end = text.find(triple, i + 3)
            end = n if end < 0 else end + 3
            blank(i + 3, end - 3)
            i = end
        elif text[i] in QUOTES[language]:
            quote = text[i]
            raw = (language == "go" and quote == "`") or (language == "cs" and text[i - 1:i] == "@")
            j = i + 1
            while j < n:
                c = text[j]
                if c == "\\" and not raw:
                    j += 2
                    continue
                if c == quote:
                    if raw and language == "cs" and text[j + 1:j + 2] == quote:
                        j += 2
                        continue
                    break
                if c == "\n" and quote != "`" and not raw:
                    break
                j += 1
            blank(i + 1, j)
            i = j + 1
        else:
            i += 1
    return "".join(out)


def _block_end(masked, start):
    """Index of the brace that closes the one at start, or len(masked) when it never closes."""
    depth = 0
    for k in range(start, len(masked)):
        if masked[k] == "{":
            depth += 1
        elif masked[k] == "}":
            depth -= 1
            if depth == 0:
                return k
    return len(masked)


def _body(masked, header_end):
    """(open brace, close brace) of the body after a type header, or None when it has none."""
    brace = masked.find("{", header_end)
    if brace < 0 or NO_BODY.search(masked, header_end, brace):
        return None
    return brace, _block_end(masked, brace)


def _flatten(text):
    """Depth-0 text of a body: nested blocks blanked, so member regexes never see method bodies."""
    out, depth = [], 0
    for c in text:
        if c == "{":
            out.append(c if depth == 0 else " ")
            depth += 1
        elif c == "}":
            depth = max(depth - 1, 0)
            out.append(c if depth == 0 else " ")
        else:
            out.append(c if depth == 0 or c == "\n" else " ")
    return "".join(out)


def _split_top(text, sep=","):
    """Split on sep outside brackets: "A<B, C>, D" -> ["A<B, C>", "D"]."""
    parts, depth, current = [], 0, []
    for c in text:
        if c in "<([{":
            depth += 1
        elif c in ">)]}":
            depth = max(depth - 1, 0)
        if c == sep and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(c)
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def _type_name(text):
    """Bare type name: "pkg.Base<T>" -> "Base", "Base()" -> "Base", "*pkg.T" -> "T"."""
    text = re.sub(r"\s+by\s+.*", "", text.strip(), flags=re.S)
    text = re.sub(r"[<\[(].*", "", text, flags=re.S).strip()
    return text.split(".")[-1].strip("?*&! ")


def _refs(text):
    """Capitalized identifiers in a type expression: candidate references to other types."""
    return set(re.findall(r"\b[A-Z]\w*", text or ""))


def _param_names(params, language):
    names = []
    for part in _split_top(params):
        part = re.sub(r"=.*", "", part, flags=re.S)
        part = re.sub(r"@\w+(?:\([^)]*\))?", " ", part)
        if language in ("kotlin", "ts", "python"):
            words = re.findall(r"\w+", part.split(":", 1)[0])
        elif language == "go":
            words = re.findall(r"\w+", part)[:1]
        else:
            words = re.findall(r"\w+", re.sub(r"\[[^\]]*\]", " ", part))
        if words and words[-1] not in ("self", "cls"):
            names.append(words[-1])
    return names


def _param_refs(params, language):
    refs = set()
    for part in _split_top(params):
        part = re.sub(r"=.*", "", part, flags=re.S)
        if language in ("kotlin", "ts", "python"):
            part = part.split(":", 1)[1] if ":" in part else ""
        refs |= _refs(part)
    return refs


def _method(name, params, ret, language):
    ret = " ".join((ret or "").split())
    return f"{name}({', '.join(_param_names(params, language))})" + (f" {ret}" if ret else "")


def _new_type(name, kind, language, file, line):
    return {
        "name": name, "kind": kind, "language": language, "file": Path(file), "line": line,
        "bases": [], "interfaces": [], "methods": [], "values": [], "depends_on": [], "embeds": [],
        "_refs": set(),
    }


def _enum_values(flat):
    values = []
    for part in _split_top(flat.split(";", 1)[0]):
        m = re.match(r"(?:\[[^\]]*\]\s*|@\w+(?:\([^)]*\))?\s*)*([A-Za-z_]\w*)", part)
        if m:
            values.append(m.group(1))
    return values


def _top_level(found):
    """[(name index, body span, type)] -> the types not declared inside another type's body."""
    spans = [span for _, span, _ in found if span]
    return [t for start, _, t in found if not any(s < start < e for s, e in spans)]


# ---------- C# ----------

CS_TYPE = re.compile(
    r"^[ \t]*(?:\[[^\]\n]*\][ \t]*)*"
    r"(?P<mods>(?:(?:public|internal|private|protected|abstract|sealed|static|partial|readonly|ref|unsafe|new|file)\s+)*)"
    r"(?P<kw>class|interface|record\s+struct|record\s+class|record|struct|enum)\s+(?P<name>\w+)"
    r"(?:\s*<[^>{;]*>)?(?:\s*\((?P<params>[^)]*)\))?"
    r"(?:\s*:\s*(?P<bases>[^{;]*?))?\s*(?:\bwhere\b[^{;]*)?(?=[{;])",
    re.MULTILINE,
)
CS_METHOD = re.compile(
    r"^[ \t]*(?:\[[^\]\n]*\][ \t]*)*"
    r"(?P<mods>(?:(?:public|private|protected|internal|static|async|virtual|override|abstract|new|sealed|extern|unsafe|partial|readonly)\s+)*)"
    r"(?P<ret>\w[\w.]*(?:\s*<[^()]*?>)?(?:\[\])*\??)\s+(?P<name>\w+)\s*(?:<[^>()]*>)?\s*\((?P<params>[^)]*)\)",
    re.MULTILINE,
)
CS_FIELD = re.compile(
    r"^[ \t]*(?:(?:private|protected|internal|public|readonly|static|const|required|volatile)\s+)+"
    r"(?P<type>\w[\w.]*(?:\s*<[^()=;]*?>)?(?:\[\])*\??)\s+\w+\s*(?:[;={]|=>)",
    re.MULTILINE,
)


def _constructor_refs(name, flat, language):
    refs = set()
    for c in re.finditer(r"\b" + re.escape(name) + r"\s*\((?P<params>[^)]*)\)", flat):
        refs |= _param_refs(c["params"], language)
    return refs


def _parse_cs(text, file):
    masked = _mask(text, "cs")
    found = []
    for m in CS_TYPE.finditer(masked):
        keyword = m["kw"].split()[0]
        kind = {"interface": "interface", "enum": "enum", "record": "record", "struct": "struct"}.get(keyword, "class")
        if kind == "class" and "abstract" in m["mods"].split():
            kind = "abstract"
        t = _new_type(m["name"], kind, "cs", file, _line_of(masked, m.start("name")))
        span = _body(masked, m.end())
        flat = _flatten(masked[span[0] + 1:span[1]]) if span else ""
        if kind == "enum":
            t["values"] = _enum_values(flat)
            found.append((m.start("name"), span, t))
            continue
        for base in (_type_name(b) for b in _split_top(m["bases"] or "")):
            if kind == "interface":
                t["bases"].append(base)
            elif not t["bases"] and not re.match(r"I[A-Z]", base):
                t["bases"].append(base)
            else:
                t["interfaces"].append(base)
        for method in CS_METHOD.finditer(flat):
            mods = method["mods"].split()
            if method["ret"] in NOT_TYPES:
                continue
            if (kind != "interface" and "public" not in mods) or "private" in mods:
                continue
            t["methods"].append(_method(method["name"], method["params"], method["ret"], "cs"))
        for field in CS_FIELD.finditer(flat):
            t["_refs"] |= _refs(field["type"])
        t["_refs"] |= _constructor_refs(m["name"], flat, "cs")
        if m["params"]:
            t["_refs"] |= _param_refs(m["params"], "cs")
        found.append((m.start("name"), span, t))
    return _top_level(found), []


# ---------- Java ----------

JAVA_TYPE = re.compile(
    r"^[ \t]*(?:@\w+(?:\([^)]*\))?\s+)*"
    r"(?P<mods>(?:(?:public|protected|private|abstract|final|static|sealed|non-sealed|strictfp)\s+)*)"
    r"(?P<kw>class|interface|enum|record)\s+(?P<name>\w+)(?:\s*<[^{]*?>)?(?:\s*\((?P<params>[^)]*)\))?"
    r"(?:\s+extends\s+(?P<ext>[^{]+?))?(?:\s+implements\s+(?P<impl>[^{]+?))?(?:\s+permits\s+[^{]+?)?\s*(?=\{)",
    re.MULTILINE,
)
JAVA_METHOD = re.compile(
    r"^[ \t]*(?:@\w+(?:\([^)]*\))?\s+)*"
    r"(?P<mods>(?:(?:public|protected|private|static|final|abstract|synchronized|default|native|strictfp)\s+)*)"
    r"(?:<[^>]+>\s+)?(?P<ret>\w[\w.]*(?:\s*<[^()]*?>)?(?:\[\])*)\s+(?P<name>\w+)\s*\((?P<params>[^)]*)\)",
    re.MULTILINE,
)
JAVA_FIELD = re.compile(
    r"^[ \t]*(?:@\w+(?:\([^)]*\))?\s+)*(?:(?:private|protected|public|final|static|transient|volatile)\s+)+"
    r"(?P<type>\w[\w.]*(?:\s*<[^()=;]*?>)?(?:\[\])*)\s+\w+\s*[;=]",
    re.MULTILINE,
)


def _parse_java(text, file):
    masked = _mask(text, "java")
    found = []
    for m in JAVA_TYPE.finditer(masked):
        kind = {"interface": "interface", "enum": "enum", "record": "record"}.get(m["kw"], "class")
        if kind == "class" and "abstract" in m["mods"].split():
            kind = "abstract"
        t = _new_type(m["name"], kind, "java", file, _line_of(masked, m.start("name")))
        span = _body(masked, m.end())
        flat = _flatten(masked[span[0] + 1:span[1]]) if span else ""
        if kind == "enum":
            t["values"] = _enum_values(flat)
            found.append((m.start("name"), span, t))
            continue
        extends = [_type_name(b) for b in _split_top(m["ext"] or "")]
        t["bases"] = extends if kind == "interface" else extends[:1]
        t["interfaces"] = [_type_name(i) for i in _split_top(m["impl"] or "")]
        for method in JAVA_METHOD.finditer(flat):
            mods = method["mods"].split()
            if method["ret"] in NOT_TYPES or "private" in mods:
                continue
            if kind != "interface" and "public" not in mods:
                continue
            t["methods"].append(_method(method["name"], method["params"], method["ret"], "java"))
        for field in JAVA_FIELD.finditer(flat):
            t["_refs"] |= _refs(field["type"])
        t["_refs"] |= _constructor_refs(m["name"], flat, "java")
        if m["params"]:
            t["_refs"] |= _param_refs(m["params"], "java")
        found.append((m.start("name"), span, t))
    return _top_level(found), []


# ---------- Kotlin ----------

KT_TYPE = re.compile(
    r"^[ \t]*(?:@\w+(?:\([^)]*\))?\s+)*"
    r"(?P<mods>(?:(?:public|internal|private|protected|abstract|open|final|sealed|data|enum|inner|value|annotation|fun|expect|actual)\s+)*)"
    r"(?P<kw>class|interface|object)\s+(?P<name>\w+)(?:\s*<[^>{]*>)?"
    r"(?:\s*(?:(?:public|internal|private|protected)\s+)?(?:@\w+\s+)?constructor)?"
    r"(?:\s*\((?P<params>(?:[^()]|\([^()]*\))*)\))?"
    r"(?:\s*:\s*(?P<bases>[^{\n]+))?",
    re.MULTILINE,
)
KT_FUN = re.compile(
    r"^[ \t]*(?:@\w+(?:\([^)]*\))?\s+)*(?P<mods>(?:\w+\s+)*?)fun\s+(?:<[^>]+>\s+)?(?:[\w.]+\.)?(?P<name>\w+)\s*"
    r"\((?P<params>(?:[^()]|\([^()]*\))*)\)(?:\s*:\s*(?P<ret>[\w.<>?, ]+?))?\s*(?:[={]|$)",
    re.MULTILINE,
)


def _parse_kotlin(text, file):
    masked = _mask(text, "kotlin")
    found = []
    for m in KT_TYPE.finditer(masked):
        mods = m["mods"].split()
        if m["kw"] == "interface":
            kind = "interface"
        elif "enum" in mods:
            kind = "enum"
        elif "data" in mods:
            kind = "record"
        elif "abstract" in mods or "sealed" in mods:
            kind = "abstract"
        else:
            kind = "class"
        t = _new_type(m["name"], kind, "kotlin", file, _line_of(masked, m.start("name")))
        span = _body(masked, m.end())
        flat = _flatten(masked[span[0] + 1:span[1]]) if span else ""
        if kind == "enum":
            t["values"] = _enum_values(flat)
            found.append((m.start("name"), span, t))
            continue
        for base in _split_top(m["bases"] or ""):
            name = _type_name(base)
            if kind == "interface" or ("(" in base and not t["bases"]):
                t["bases"].append(name)
            else:
                t["interfaces"].append(name)
        for fun in KT_FUN.finditer(flat):
            if set(fun["mods"].split()) & {"private", "internal", "protected"}:
                continue
            t["methods"].append(_method(fun["name"], fun["params"], fun["ret"], "kotlin"))
        if m["params"]:
            t["_refs"] |= _param_refs(m["params"], "kotlin")
        found.append((m.start("name"), span, t))
    return _top_level(found), []


# ---------- Go ----------

GO_TYPE = re.compile(r"^type\s+(?P<name>\w+)(?:\[[^\]]*\])?\s+(?P<kw>struct|interface)\s*\{", re.MULTILINE)
GO_FUNC = re.compile(
    r"^func\s+\(\s*(?:\w+\s+)?\*?(?P<recv>\w+)(?:\[[^\]]*\])?\s*\)\s+(?P<name>[A-Z]\w*)\s*\((?P<params>[^)]*)\)\s*(?P<ret>[^{\n]*)",
    re.MULTILINE,
)
GO_FIELD = re.compile(r"^(\w+(?:\s*,\s*\w+)*)\s+(\S.*)$")
GO_IFACE_METHOD = re.compile(r"^([A-Z]\w*)\s*\(([^)]*)\)\s*(.*)$")


def _parse_go(text, file):
    masked = _mask(text, "go")
    types = []
    for m in GO_TYPE.finditer(masked):
        kind = m["kw"]
        t = _new_type(m["name"], kind, "go", file, _line_of(masked, m.start("name")))
        brace = m.end() - 1
        flat = _flatten(masked[brace + 1:_block_end(masked, brace)])
        for line in re.split(r"[\n;]", flat):
            line = line.strip()
            if not line:
                continue
            if kind == "struct":
                field = GO_FIELD.match(line)
                if field and not field.group(2).startswith("`"):
                    t["_refs"] |= _refs(field.group(2))
                else:
                    t["embeds"].append(_type_name(line.split()[0]))
            else:
                method = GO_IFACE_METHOD.match(line)
                if method:
                    t["methods"].append(_method(method[1], method[2], method[3], "go"))
                elif re.fullmatch(r"\*?[\w.]+", line):
                    t["bases"].append(_type_name(line))
        types.append(t)
    methods = [(f["recv"], _method(f["name"], f["params"], f["ret"], "go")) for f in GO_FUNC.finditer(masked)]
    return types, methods


# ---------- Python ----------

PY_CLASS = re.compile(r"^class\s+(?P<name>\w+)\s*(?:\[[^\]]*\])?\s*(?:\((?P<bases>[^)]*)\))?\s*:", re.MULTILINE)
PY_DEF = re.compile(
    r"^(?P<indent>[ \t]+)(?:async\s+)?def\s+(?P<name>\w+)\s*\((?P<params>[^)]*)\)\s*(?:->\s*(?P<ret>[^:]+?))?\s*:",
    re.MULTILINE,
)
PY_ENUMS = {"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"}
PY_SKIPPED_BASES = {"object", "ABC", "Protocol", "Generic"} | PY_ENUMS


def _parse_python(text, file):
    masked = _mask(text, "python")
    types = []
    for m in PY_CLASS.finditer(masked):
        raw_bases = text[m.start("bases"):m.end("bases")] if m["bases"] is not None else ""
        names = [_type_name(b) for b in _split_top(raw_bases) if "=" not in b]
        if set(names) & PY_ENUMS:
            kind = "enum"
        elif "Protocol" in names:
            kind = "interface"
        elif "ABC" in names or "ABCMeta" in raw_bases:
            kind = "abstract"
        elif re.search(r"^@(?:dataclasses\.)?dataclass\b[^\n]*\n\Z", masked[:m.start()], re.MULTILINE):
            kind = "record"
        else:
            kind = "class"
        t = _new_type(m["name"], kind, "python", file, _line_of(masked, m.start("name")))
        t["bases"] = [n for n in names if n not in PY_SKIPPED_BASES]
        start = masked.find("\n", m.end()) + 1 if "\n" in masked[m.end():] else len(masked)
        after = re.compile(r"^\S", re.MULTILINE).search(masked, start)
        end = after.start() if after else len(masked)
        first = re.search(r"^([ \t]+)\S", masked[start:end], re.MULTILINE)
        indent = first.group(1) if first else None
        if indent is not None:
            for d in PY_DEF.finditer(masked, start, end):
                if d["indent"] != indent:
                    continue
                params = text[d.start("params"):d.end("params")]
                ret = text[d.start("ret"):d.end("ret")] if d["ret"] is not None else ""
                if d["name"] == "__init__":
                    t["_refs"] |= _param_refs(params, "python")
                if not d["name"].startswith("_"):
                    t["methods"].append(_method(d["name"], params, ret.strip("\"' "), "python"))
            body = text[start:end]
            for a in re.finditer(rf"^{indent}(\w+)\s*:\s*([^=\n]+)", body, re.MULTILINE):
                t["_refs"] |= _refs(a.group(2))
            if kind == "enum":
                t["values"] = re.findall(rf"^{indent}([A-Z_][A-Z0-9_]*)\s*=", masked[start:end], re.MULTILINE)
        types.append(t)
    return types, []


# ---------- TypeScript / JavaScript ----------

TS_TYPE = re.compile(
    r"^[ \t]*(?:@\w+(?:\([^)]*\))?\s+)*(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:const\s+)?"
    r"(?P<abstract>abstract\s+)?(?P<kw>class|interface|enum)\s+(?P<name>\w+)(?:\s*<[^{]*?>)?"
    r"(?:\s+extends\s+(?P<ext>[^{]+?))?(?:\s+implements\s+(?P<impl>[^{]+?))?\s*(?=\{)",
    re.MULTILINE,
)
TS_METHOD = re.compile(
    r"^[ \t]*(?:@\w+(?:\([^)]*\))?\s+)*"
    r"(?P<mods>(?:(?:public|private|protected|static|async|abstract|readonly|override|declare)\s+)*)\*?\s*"
    r"(?P<name>#?\w+)\s*(?:<[^>()]*>)?\s*\((?P<params>[^)]*)\)\s*(?::\s*(?P<ret>[^{;=]+?))?\s*(?:[{;]|=>|$)",
    re.MULTILINE,
)
TS_IFACE_METHOD = re.compile(
    r"^[ \t]*(?:readonly\s+)?(?P<name>\w+)\??\s*(?:<[^>()]*>)?\s*\((?P<params>[^)]*)\)\s*:\s*(?P<ret>[^;\n]+)",
    re.MULTILINE,
)
TS_NOT_METHODS = {"constructor", "if", "for", "while", "switch", "catch", "return", "function", "super"}


def _parse_ts(text, file):
    masked = _mask(text, "ts")
    found = []
    for m in TS_TYPE.finditer(masked):
        kind = {"interface": "interface", "enum": "enum"}.get(m["kw"], "abstract" if m["abstract"] else "class")
        t = _new_type(m["name"], kind, "ts", file, _line_of(masked, m.start("name")))
        span = _body(masked, m.end())
        flat = _flatten(masked[span[0] + 1:span[1]]) if span else ""
        if kind == "enum":
            t["values"] = _enum_values(flat)
            found.append((m.start("name"), span, t))
            continue
        t["bases"] = [_type_name(b) for b in _split_top(m["ext"] or "")]
        t["interfaces"] = [_type_name(i) for i in _split_top(m["impl"] or "")]
        if kind == "interface":
            for method in TS_IFACE_METHOD.finditer(flat):
                t["methods"].append(_method(method["name"], method["params"], method["ret"].strip().rstrip(","), "ts"))
        else:
            for method in TS_METHOD.finditer(flat):
                mods = set(method["mods"].split())
                if method["name"] in TS_NOT_METHODS or method["name"].startswith("#") or mods & {"private", "protected"}:
                    continue
                t["methods"].append(_method(method["name"], method["params"], method["ret"], "ts"))
            t["_refs"] |= _constructor_refs("constructor", flat, "ts")
        found.append((m.start("name"), span, t))
    return _top_level(found), []


PARSERS = {
    "cs": _parse_cs, "java": _parse_java, "kotlin": _parse_kotlin, "go": _parse_go,
    "python": _parse_python, "ts": _parse_ts,
}


def _merge(types, new):
    """Add a type; a second declaration of the same name (partial class, another namespace) is merged."""
    old = types.get(new["name"])
    if old is None:
        types[new["name"]] = new
        return
    for key in ("bases", "interfaces", "methods", "values", "embeds"):
        old[key] += [v for v in new[key] if v not in old[key]]
    old["_refs"] |= new["_refs"]


def extract(files):
    """{type name: type} for the given source files (generated files and unknown languages are skipped)."""
    types, receiver_methods = {}, []
    for file in files:
        file = Path(file)
        parser = PARSERS.get(LANGUAGES.get(file.suffix.lower()))
        if parser is None or is_generated(file.name):
            continue
        found, methods = parser(_load_source(file), file)
        receiver_methods += methods
        for t in found:
            _merge(types, t)
    for receiver, method in receiver_methods:  # Go: methods can live in another file of the package
        if receiver in types and method not in types[receiver]["methods"]:
            types[receiver]["methods"].append(method)
    names = set(types)
    for t in types.values():
        related = set(t["bases"]) | set(t["interfaces"]) | set(t["embeds"]) | {t["name"]}
        t["depends_on"] = sorted((t.pop("_refs") & names) - related)
    return dict(sorted(types.items()))
