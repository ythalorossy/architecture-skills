"""Paths and sys.path setup for the architecture-review tests.

This suite is self-contained: it reads nothing from the shared `tests/`
folder or from c4-diagrams. Its fixtures live in `fixtures/` here, including
a frozen copy of the c4 facts for the fixture repository, so a change in
c4-diagrams cannot break these tests (and these tests need no c4 run).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent.parent
SKILL = PLUGIN_ROOT / "skills" / "architecture-review"
FIXTURE_REPO = HERE / "fixtures" / "repos" / "architecture-review-mvp"
FIXTURE_FACTS = HERE / "fixtures" / "facts" / "architecture-review-mvp.c4-facts.json"
TRIGGERS = HERE / "triggers.jsonl"

# Only this skill's `scripts` package belongs on the path.
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))
