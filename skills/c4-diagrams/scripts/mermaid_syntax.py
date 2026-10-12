"""
Mermaid syntax in one place:
id allocation per diagram kind, text escaping per diagram kind, the front-matter
title, and the C4 palette.
"""
import json
import re


# ---------------------------------------------------------------------------
# Keyword sets (moved from code_diagrams.MERMAID_WORDS, extended)
# ---------------------------------------------------------------------------

FLOWCHART_KEYWORDS = {
    "end", "graph", "subgraph", "style", "class", "classDef", "click",
    "call", "linkStyle", "flowchart", "href", "interpolate",
    # aliases used internally
    "End", "END",
}
SEQUENCE_KEYWORDS = {
    "end", "loop", "alt", "opt", "par", "rect", "note", "participant",
    "actor", "box", "critical", "break", "else", "and", "activate",
    "deactivate", "autonumber", "create", "destroy", "over",
}
# classDiagram has additional keywords beyond the flowchart set
CLASS_KEYWORDS = FLOWCHART_KEYWORDS | {
    "classdef", "cssclass", "classdiagram", "note", "link", "callback",
    "namespace", "direction",
}


# ---------------------------------------------------------------------------
# IdAllocator
# ---------------------------------------------------------------------------

_ID_CHARS = re.compile(r"[^A-Za-z0-9_]")


class IdAllocator:
    """
    Allocate Mermaid ids for one diagram.

    ``kind`` is ``"flowchart"``, ``"sequence"`` or ``"class"``; each has its
    own reserved words. The id is a readable slug of the key (``db-sql-server``
    becomes ``db_sql_server``). If that slug is a reserved word, or another
    key in the same diagram already has it, a numeric suffix is added
    (``db_sql_server_2``), so two different keys never share an id.

    Use one allocator per diagram, for element ids and internal nodes
    (boundaries, module boxes) alike, so they can't collide either.
    """

    # Internal keys start with a character no model or fact id contains.
    _INTERNAL = "\x00"

    def __init__(self, kind: str):
        if kind not in ("flowchart", "sequence", "class"):
            raise ValueError(f"Unknown diagram kind: {kind!r}")
        keywords = {
            "flowchart": FLOWCHART_KEYWORDS,
            "sequence": SEQUENCE_KEYWORDS,
            "class": CLASS_KEYWORDS,
        }[kind]
        self._keywords = {k.lower() for k in keywords}
        self._ids: dict[str, str] = {}
        self._used: set[str] = set()

    def __contains__(self, key: str) -> bool:
        """True once ``key`` has an id in this diagram."""
        return key in self._ids

    def id(self, key: str) -> str:
        """Return the id for ``key``; the same key always gets the same id."""
        if key in self._ids:
            return self._ids[key]
        base = _ID_CHARS.sub("_", key).strip("_") or "node"
        if base[0].isdigit():
            base = f"n_{base}"
        candidate = base
        suffix = 2
        while candidate in self._used or candidate.lower() in self._keywords:
            candidate = f"{base}_{suffix}"
            suffix += 1
        self._used.add(candidate)
        self._ids[key] = candidate
        return candidate

    def internal(self, name: str) -> str:
        """Id for an internal node (system boundary, module box, …)."""
        return self.id(self._INTERNAL + name)

    @classmethod
    def internal_key(cls, name: str) -> str:
        """Key to pass to ``id`` (or a diagram's node/edge) for an internal node."""
        return cls._INTERNAL + name


def safe_id(kind: str, key: str) -> str:
    """One-shot safe id for ``key`` in the given diagram kind."""
    return IdAllocator(kind).id(key)


# ---------------------------------------------------------------------------
# Text escapers
# ---------------------------------------------------------------------------
# Each escaper is a single-pass str.translate(table) built once at module load.
# The tables map ordinals of characters to be escaped → the Mermaid entity code.
# Wrapping (textwrap) is applied *before* escaping, so it stays in render_c4._wrap.

# flowchart markdown: escape * ~ " < > in label text; # %% at line start
# Note: _ is NOT escaped here because __main__ etc. are Python names that
# should survive unchanged — Mermaid does not use _ for formatting in labels.
# We use a character-by-character loop (not str.maketrans) because:
#   - * and ~ need a literal backslash prepended
#   - " < > need Mermaid entity codes
#   - Leading # or %% on a wrapped line need a leading backslash

def flowchart_md_escape(text: str) -> str:
    """Escape Markdown metacharacters and entity chars in a flowchart label string.

    Wrapping (textwrap) is applied *before* this in render_c4._wrap, so
    leading # or %% on a wrapped line are handled here by prepending a
    backslash to the first character of each line.
    """
    # Step 1: escape leading # or %% on each line (for wrapped text)
    escaped = _escape_leading_special_chars(text)
    # Step 2: escape * ~ " < >
    return _escape_md_metachars(escaped)


def _escape_leading_special_chars(text: str) -> str:
    """Prepend \\ to a # or %% at the start of any line (for wrapped text)."""
    lines = text.split("\n")
    result = []
    for line in lines:
        if line and (line.startswith("#") or line.startswith("%%")):
            line = "\\" + line
        result.append(line)
    return "\n".join(result)


def _curly_quotes(text: str) -> str:
    """
    Straight double quotes as “…”. In flowchart labels mermaid shows #quot;
    literally (as &quot;) and a raw " ends the label, so typographic quotes
    are the only way to show quotation marks there.
    """
    out, opening = [], True
    for c in text:
        if c == '"':
            out.append("“" if opening else "”")
            opening = not opening
        else:
            out.append(c)
    return "".join(out)


def _escape_md_metachars(text: str) -> str:
    """Escape * ~ " < > to Mermaid-interpretable form (character-by-character)."""
    out = []
    for c in _curly_quotes(text):
        if c == "*":
            out.append(r"\*")
        elif c == "~":
            out.append(r"\~")
        elif c == "<":
            out.append("#lt;")
        elif c == ">":
            out.append("#gt;")
        elif c == "`":
            # A backtick would end the "`…`" markdown string, and mermaid
            # shows #96; literally there, so use an apostrophe.
            out.append("'")
        else:
            out.append(c)
    return "".join(out)


# flowchart plain: entity codes for < >, typographic quotes for "
_FLOWCHART_PLAIN_TABLE = str.maketrans({
    '<': "#lt;",
    '>': "#gt;",
    # Plain text is also placed inside "`…`" strings (titles, edge labels).
    '`': "'",
})

def flowchart_plain_escape(text: str) -> str:
    """Escape " < > for a plain (non-markdown) flowchart label."""
    return _curly_quotes(text).translate(_FLOWCHART_PLAIN_TABLE)


# sequence message: escape # and ; in a single pass (no double-escaping)
_SEQUENCE_MSG_TABLE = str.maketrans({
    "#":  "#35;",
    ";":  "#59;",
})

def sequence_msg_escape(text: str) -> str:
    """Escape # and ; in a sequence diagram message in a single pass."""
    return text.translate(_SEQUENCE_MSG_TABLE)


# sequence alias: same as message plus "
_SEQUENCE_ALIAS_TABLE = str.maketrans({
    "#":  "#35;",
    ";":  "#59;",
    '"':  "#quot;",
})

def sequence_alias_escape(text: str) -> str:
    """Escape # ; " in a sequence diagram participant alias in a single pass."""
    return text.translate(_SEQUENCE_ALIAS_TABLE)


# class member: entity codes for < >
_CLASS_MEMBER_TABLE = str.maketrans({
    "<":  "#lt;",
    ">":  "#gt;",
})

def class_member_escape(text: str) -> str:
    """Escape < > to Mermaid entity codes in a class member signature."""
    return text.translate(_CLASS_MEMBER_TABLE)


# ---------------------------------------------------------------------------
# Public label_text dispatcher
# ---------------------------------------------------------------------------

def label_text(kind: str, text: str) -> str:
    """
    Escape ``text`` for the given diagram kind.

    ``kind`` one of: ``flowchart_md`` (markdown string label), ``flowchart_plain``
    (plain label), ``sequence_msg`` (message/note text), ``sequence_alias``
    (participant alias), ``class_member`` (class diagram member).
    """
    if text is None:
        return ""
    if kind == "flowchart_md":
        return flowchart_md_escape(str(text))
    elif kind == "flowchart_plain":
        return flowchart_plain_escape(str(text))
    elif kind == "sequence_msg":
        return sequence_msg_escape(str(text))
    elif kind == "sequence_alias":
        return sequence_alias_escape(str(text))
    elif kind == "class_member":
        return class_member_escape(str(text))
    else:
        raise ValueError(f"Unknown label kind: {kind!r}")


# ---------------------------------------------------------------------------
# C4 palette (single source for both flowchart classDef and classDiagram style)
# ---------------------------------------------------------------------------

C4_PALETTE = {
    "person":     "#08427b",
    "person_stroke": "#052e56",
    "person_text": "#ffffff",

    "container":  "#1168bd",
    "container_stroke": "#0b4884",
    "container_text": "#ffffff",

    "system":     "#1168bd",   # same colour as container (C4 convention)
    "system_stroke": "#0b4884",
    "system_text": "#ffffff",

    "component":  "#85bbf0",
    "component_stroke": "#5d82a8",
    "component_text": "#000000",

    "external":   "#999999",
    "external_stroke": "#6b6b6b",
    "external_text": "#ffffff",

    "shared":     "#dbe9f6",
    "shared_stroke": "#5d82a8",
    "shared_text": "#000000",

    # The dashed outline around a system or container boundary, and the
    # pale box a folder of components is drawn in.
    "boundary_stroke": "#444444",
    "folder":     "#f4f8fc",
    "folder_stroke": "#9fb6cc",
}


def boundary_style() -> str:
    """Mermaid ``style`` body for a system or container boundary."""
    return f"fill:none,stroke:{C4_PALETTE['boundary_stroke']},stroke-dasharray:6 4"


def folder_style() -> str:
    """Mermaid ``style`` body for the box around one folder of components."""
    return f"fill:{C4_PALETTE['folder']},stroke:{C4_PALETTE['folder_stroke']}"

# Formatted classDef lines (flowchart)
def flowchart_classdef_lines() -> list[str]:
    """Mermaid ``classDef`` lines for all C4 styles."""
    return [
        f"classDef person fill:{C4_PALETTE['person']},stroke:{C4_PALETTE['person_stroke']},color:{C4_PALETTE['person_text']}",
        f"classDef container fill:{C4_PALETTE['container']},stroke:{C4_PALETTE['container_stroke']},color:{C4_PALETTE['container_text']}",
        f"classDef system fill:{C4_PALETTE['system']},stroke:{C4_PALETTE['system_stroke']},color:{C4_PALETTE['system_text']}",
        f"classDef component fill:{C4_PALETTE['component']},stroke:{C4_PALETTE['component_stroke']},color:{C4_PALETTE['component_text']}",
        f"classDef external fill:{C4_PALETTE['external']},stroke:{C4_PALETTE['external_stroke']},color:{C4_PALETTE['external_text']}",
        f"classDef shared fill:{C4_PALETTE['shared']},stroke:{C4_PALETTE['shared_stroke']},color:{C4_PALETTE['shared_text']},stroke-dasharray:4 3",
    ]


# Component / shared style strings (classDiagram per-box style lines)
def component_style() -> str:
    return (
        f"fill:{C4_PALETTE['component']},stroke:{C4_PALETTE['component_stroke']},"
        f"color:{C4_PALETTE['component_text']}"
    )

def shared_style() -> str:
    return (
        f"fill:{C4_PALETTE['shared']},stroke:{C4_PALETTE['shared_stroke']},"
        f"color:{C4_PALETTE['shared_text']},stroke-dasharray:4 3"
    )


def with_title(mermaid: str, title: str) -> str:
    """The diagram with a front-matter ``title``, so a shared `.mmd` says what it is.

    JSON quoting is YAML's double-quoted scalar: a colon, a quote or a
    backslash in a container name cannot end the header early. Non-ASCII
    characters are left as they are, so a name stays readable in the file.
    A diagram that already carries front matter (Level 4 sets a renderer
    option) gets the title added to it rather than a second header.
    """
    header = f"title: {json.dumps(str(title), ensure_ascii=False)}\n"
    if mermaid.startswith("---\n"):
        return "---\n" + header + mermaid[len("---\n"):]
    return "---\n" + header + "---\n" + mermaid
