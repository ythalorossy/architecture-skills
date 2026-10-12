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


def _component_owner(model):
    """{component key: owning container id} from the model's `components` map.

    Flow steps name components, not containers ("bookshop.orders"), so a step
    end has to be mapped to its container before a container role can match.
    """
    owners = {}
    components = model.get("components")
    if isinstance(components, dict):
        for container_id, entries in components.items():
            if isinstance(entries, dict):
                for component in entries:
                    owners.setdefault(component, container_id)
    return owners


def _end_role(end, role_of, owners=None):
    """The gold role an edge end belongs to, or None.

    `owners` is passed for flow steps only. It is applied *before* the role
    lookup on purpose: "web/src/api" contains the substring "api" but is a
    module of the web app, so matching first would score it as the API.
    """
    if end is None:
        return None
    end = str(end)
    if owners:
        end = owners.get(end, end)
    return role_of.get(end)


def _edge_roles(edges, role_of, owners=None):
    """{(from role, to role)} for the edges whose ends both resolve."""
    pairs = set()
    for edge in edges or []:
        if not isinstance(edge, dict):
            continue
        source = _end_role(edge.get("from"), role_of, owners)
        target = _end_role(edge.get("to"), role_of, owners)
        if source and target:
            pairs.add((source, target))
    return pairs


def _flow_steps(model):
    """Every step of every flow, flattened."""
    steps = []
    for flow in model.get("flows") or []:
        if isinstance(flow, dict):
            steps.extend(flow.get("steps") or [])
    return steps


def score_recall(model, gold):
    """How much of the gold this model contains.

    Three parts, summed into one score: the required elements, the required
    relationships (direction significant — a reversed arrow is wrong) and the
    required flow steps (order within a flow is not checked).
    """
    matched_roles = resolve_roles(model, gold)
    role_of = _role_of(matched_roles)
    owners = _component_owner(model)
    missed = []

    elements = gold["required_elements"]
    element_hits = 0
    for entry in elements:
        if entry["role"] in matched_roles:
            element_hits += 1
        else:
            missed.append(f"element {entry['role']}")

    relationship_pairs = _edge_roles(model.get("relationships"), role_of)
    relationship_hits = 0
    for pair in gold["required_relationships"]:
        if tuple(pair) in relationship_pairs:
            relationship_hits += 1
        else:
            missed.append(f"relationship {pair[0]} -> {pair[1]}")

    step_pairs = _edge_roles(_flow_steps(model), role_of, owners)
    step_hits = 0
    for pair in gold["required_flow_steps"]:
        if tuple(pair) in step_pairs:
            step_hits += 1
        else:
            missed.append(f"flow step {pair[0]} -> {pair[1]}")

    parts = {
        "elements": (element_hits, len(elements)),
        "relationships": (relationship_hits, len(gold["required_relationships"])),
        "flow_steps": (step_hits, len(gold["required_flow_steps"])),
    }
    hits = element_hits + relationship_hits + step_hits
    total = sum(count for _, count in parts.values())
    return {
        "score": hits / total if total else 1.0,
        "hits": hits,
        "total": total,
        "parts": parts,
        "missed": missed,
    }


def score_hallucination(model, gold, drift):
    """Count the things in this model that are not in the repository.

    Two sources: an element whose id or name hits a `forbidden` term from the
    gold, and the `drift` lines `render_c4.validate` already produces for
    elements that cover no fact and are not marked `assumption`.

    A count, not a ratio. The denominator would be arbitrary, and dividing by
    the number of elements would reward padding the model with correct boxes.
    """
    problems = []
    forbidden = [str(term).lower() for term in gold["forbidden"]]
    for _, _, element in _elements(model):
        text = _haystack(element)
        hit = next((term for term in forbidden if term in text), None)
        if hit:
            name = element.get("name") or element.get("id") or "?"
            problems.append(f"forbidden {hit!r}: {name}")
    problems.extend(f"drift: {message}" for message in drift or [])
    return {"count": len(problems), "problems": problems}
