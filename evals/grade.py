"""Score a candidate c4-model.json against a criteria gold file.

Four measures: recall of the gold's required elements, relationships and
flow steps; a count of hallucinations; the fraction of evidence entries
that point at a real file and line; and whether the model renders.

The scorer imports the skill's own `validate`, `_evidence_problem` and
`render` rather than reimplementing them — a copy would drift away from
the thing it claims to measure. `_evidence_problem` is private to
render_c4; reusing it here is deliberate and is what BACKLOG B-08 asks for.

This is a development tool. Nothing under evals/ is imported by the skill
at runtime, and the shipped skill stays stdlib-only scripts.
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "c4-diagrams"
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from scripts.cli_support import UserError  # noqa: E402  (sys.path is set above)


def load_gold(path):
    """Parse a gold file and check it is well formed.

    Raises UserError naming the file for: unreadable or non-JSON content, an
    empty `required_elements`, a duplicate role, a relationship or flow-step
    end that is not a declared role, a `match` term claimed by two roles, or
    a `forbidden` term that overlaps a `match` term.

    The last two matter most: a shared match term makes role resolution
    depend on gold order, and an overlapping forbidden term scores a correct
    answer as a hallucination. Neither would look wrong in the output.
    """
    path = Path(path)
    label = str(path)
    try:
        gold = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise UserError(f"cannot read ({exc})", path=label) from exc
    except json.JSONDecodeError as exc:
        raise UserError(f"not valid JSON: {exc}", path=label) from exc
    if not isinstance(gold, dict):
        raise UserError("expected a JSON object", path=label)

    elements = gold.get("required_elements") or []
    if not elements:
        raise UserError("required_elements is empty", path=label)

    roles = [element.get("role") for element in elements]
    duplicates = sorted({role for role in roles if roles.count(role) > 1})
    if duplicates:
        raise UserError(f"duplicate role(s): {', '.join(str(r) for r in duplicates)}", path=label)

    known = set(roles)
    for key in ("required_relationships", "required_flow_steps"):
        for pair in gold.get(key) or []:
            for end in pair:
                if end not in known:
                    raise UserError(f"{key}: {end!r} is not a declared role", path=label)

    owner_of_term = {}
    for element in elements:
        for term in element.get("match") or []:
            term = str(term).lower()
            if term in owner_of_term:
                raise UserError(
                    f"match term {term!r} is claimed by both {owner_of_term[term]!r} "
                    f"and {element['role']!r}",
                    path=label,
                )
            owner_of_term[term] = element["role"]

    for entry in gold.get("forbidden") or []:
        forbidden = str(entry).lower()
        for term, role in owner_of_term.items():
            if forbidden in term or term in forbidden:
                raise UserError(
                    f"forbidden term {entry!r} overlaps the match term {term!r} "
                    f"of role {role!r}",
                    path=label,
                )

    gold.setdefault("required_relationships", [])
    gold.setdefault("required_flow_steps", [])
    gold.setdefault("forbidden", [])
    return gold


SECTIONS = ("people", "containers", "external_systems")


def _elements(model):
    """[(section, index, element)] in document order, skipping non-dict entries.

    Document order is people, then containers, then external_systems, each in
    file order. It is what makes "the first candidate wins" reproducible.
    """
    found = []
    for section in SECTIONS:
        for index, element in enumerate(model.get(section) or []):
            if isinstance(element, dict):
                found.append((section, index, element))
    return found


def _haystack(element):
    """The element's id and name, lower-cased, for substring matching."""
    return f"{element.get('id') or ''}\n{element.get('name') or ''}".lower()


def resolve_roles(model, gold):
    """{role: element id} for the gold roles this model satisfies.

    Roles are tried in gold order; candidates in document order; the first
    unclaimed match wins and is then unavailable to later roles. Without that
    last rule one container called "Bookshop API Web" would satisfy both
    `web-ui` and `api`, and recall would be inflated by a model that is
    missing a container.

    `kind` is not checked. Calling the catalogue index an external system
    rather than a database is a modelling choice, not a miss.
    """
    candidates = _elements(model)
    claimed = set()
    matched = {}
    for entry in gold["required_elements"]:
        terms = [str(term).lower() for term in entry.get("match") or []]
        for section, index, element in candidates:
            if (section, index) in claimed or not element.get("id"):
                continue
            text = _haystack(element)
            if any(term in text for term in terms):
                matched[entry["role"]] = element.get("id")
                claimed.add((section, index))
                break
    return matched


def _role_of(matched):
    """{element id: role}, the reverse of resolve_roles' result."""
    return {element_id: role for role, element_id in matched.items() if element_id}
