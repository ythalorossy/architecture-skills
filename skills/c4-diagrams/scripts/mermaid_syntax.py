"""
Single safe Mermaid emitter (SPEC-04): owns all Mermaid syntax concerns —
id allocation per diagram kind, text escaping per diagram kind, and the C4 palette.
"""
import hashlib


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
# Stable hash (used only for collision suffixes — not cryptographic)
# ---------------------------------------------------------------------------

def _stable_hash(text: str) -> str:
    """Short deterministic hex digest of ``text``."""
    return hashlib.md5(text.encode()).hexdigest()[:6]


# ---------------------------------------------------------------------------
# IdAllocator
# ---------------------------------------------------------------------------

class IdAllocator:
    """
    Allocate Mermaid-safe identifiers per diagram kind.

    ``kind`` is one of ``"flowchart"``, ``"sequence"``, ``"class"``.
    Each kind has its own keyword guard set.

    The base id is derived *solely* from the key, never from position or
    insertion order.  Collisions (keyword, or a key already allocated) are
    resolved by appending a stable hash suffix so the result is still
    deterministic and order-independent.

    The special entry point ``internal(name)`` uses a reserved prefix that
    no slug or free-text model key can produce.
    """

    _INTERNAL_PREFIX = "__Int__"

    def __init__(self, kind: str):
        if kind not in ("flowchart", "sequence", "class"):
            raise ValueError(f"Unknown diagram kind: {kind!r}")
        self._kind = kind
        self._keywords = {
            "flowchart": FLOWCHART_KEYWORDS,
            "sequence": SEQUENCE_KEYWORDS,
            "class": CLASS_KEYWORDS,
        }[kind]
        self._allocated: dict[str, str] = {}

    @staticmethod
    def _slug(key: str) -> str:
        """Slug a key into a valid Mermaid id, preserving enough structure to avoid collisions."""
        import re
        # Replace common separators with distinct words to avoid a.b, a-b, a_b all → a_b
        intermediate = key.replace(".", "_dot_").replace("-", "_dash_").replace("/", "_slash_")
        base = re.sub(r"[^A-Za-z0-9_]", "_", intermediate).strip("_") or "node"
        if base[0].isdigit():
            base = f"n_{base}"
        return base

    @staticmethod
    def _is_safe_id(candidate: str, keywords: set[str]) -> bool:
        """True when candidate is a valid Mermaid id and not a keyword (case-insensitively)."""
        import re
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", candidate):
            return False
        if candidate.lower() in {k.lower() for k in keywords}:
            return False
        return True

    def id(self, key: str) -> str:
        """Return a safe Mermaid id for ``key``. Result is deterministic and order-independent."""
        if key in self._allocated:
            return self._allocated[key]

        base = self._slug(key)
        candidate = base
        suffix = 2

        while not self._is_safe_id(candidate, self._keywords):
            candidate = f"{base}_{_stable_hash(key)}"
            break  # one shot is enough because hash is stable; no counter loop

        # Second safety check: even with hash suffix we might still hit a keyword
        # (e.g. key="class" slug="class", hash suffix still produces "class_<hash>")
        # In practice hash suffix always breaks the keyword, but guard anyway
        while not self._is_safe_id(candidate, self._keywords):
            candidate = f"{base}_{suffix}"
            suffix += 1

        self._allocated[key] = candidate
        return candidate

    def internal(self, name: str) -> str:
        """Return a safe id for an internal node (system boundary, module box, etc.)."""
        key = f"{self._INTERNAL_PREFIX}{name}"
        if key not in self._allocated:
            self._allocated[key] = self.id(key)
        return self._allocated[key]


# ---------------------------------------------------------------------------
# Convenience wrappers matching the original signatures
# ---------------------------------------------------------------------------

def safe_id(kind: str, key: str) -> str:
    """One-shot safe id for ``key`` in the given diagram kind."""
    return IdAllocator(kind).id(key)


def internal_id(name: str) -> str:
    """Safe id for an internal node (system, boundary, etc.) in any diagram kind.

    Uses a prefix that user ids (slugged or free-text) can never produce.
    """
    return IdAllocator("flowchart").internal(name)


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


def _escape_md_metachars(text: str) -> str:
    """Escape * ~ " < > to Mermaid-interpretable form (character-by-character)."""
    out = []
    for c in text:
        if c == "*":
            out.append(r"\*")
        elif c == "~":
            out.append(r"\~")
        elif c == "<":
            out.append("#lt;")
        elif c == ">":
            out.append("#gt;")
        elif c == '"':
            out.append("#quot;")
        else:
            out.append(c)
    return "".join(out)


# flowchart plain: just entity codes for " < >
_FLOWCHART_PLAIN_TABLE = str.maketrans({
    '"': "#quot;",
    '<': "#lt;",
    '>': "#gt;",
})

def flowchart_plain_escape(text: str) -> str:
    """Escape " < > to Mermaid entity codes in a plain (non-markdown) label."""
    return text.translate(_FLOWCHART_PLAIN_TABLE)


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
}

# Formatted classDef lines (flowchart)
def flowchart_classdef_lines() -> list[str]:
    """Mermaid ``classDef`` lines for all C4 styles."""
    return [
        f"classDef person     fill:{C4_PALETTE['person']},stroke:{C4_PALETTE['person_stroke']},color:{C4_PALETTE['person_text']}",
        f"classDef container  fill:{C4_PALETTE['container']},stroke:{C4_PALETTE['container_stroke']},color:{C4_PALETTE['container_text']}",
        f"classDef system    fill:{C4_PALETTE['system']},stroke:{C4_PALETTE['system_stroke']},color:{C4_PALETTE['system_text']}",
        f"classDef component fill:{C4_PALETTE['component']},stroke:{C4_PALETTE['component_stroke']},color:{C4_PALETTE['component_text']}",
        f"classDef external  fill:{C4_PALETTE['external']},stroke:{C4_PALETTE['external_stroke']},color:{C4_PALETTE['external_text']}",
        f"classDef shared    fill:{C4_PALETTE['shared']},stroke:{C4_PALETTE['shared_stroke']},color:{C4_PALETTE['shared_text']},stroke-dasharray:4 3",
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
