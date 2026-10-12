"""
Lint for the one file that is purely a prompt: skills/c4-diagrams/SKILL.md.

Nothing else checks it. The scripts have golden tests; the instructions the
agent actually reads have had none, so three failures could ship unnoticed:

* a `<skill>/assets/...` pointer to a file that was renamed or never written,
  which the agent follows into a dead end;
* a `description:` the harness cannot parse, or one that stops saying when
  *not* to fire (``index.js``'s frontmatter parser reads single-line scalars
  only, so a folded ``>-`` block silently empties the description);
* unbounded growth. The file is the skill's whole prompt and competes for
  context with the repository being analysed, so it has a word budget.

The budget is deliberately a hard number rather than a ratchet: a ratchet
drifts upward one commit at a time, which is how this file reached 2,091
words.
"""
import re
import unittest

from helpers import SKILL

SKILL_MD = SKILL / "SKILL.md"

# The budget from BACKLOG B-13, counted the way the backlog counted it:
# whitespace-separated tokens over the whole file, frontmatter included.
WORD_BUDGET = 1700

# `<skill>/assets/x.md` and `<skill>/scripts/x.py`, the only two shapes used.
REFERENCE = re.compile(r"<skill>/((?:assets|scripts)/[A-Za-z0-9_.-]+\.(?:md|py))")

# A path under assets/ or scripts/ written *without* the `<skill>/` prefix.
# The working directory is the user's repository, so such a path resolves to
# the wrong place (or nowhere) when the agent runs the command. The ellipsis
# forms in the prose that explains this rule carry no file extension and so
# are not matched.
BARE_PATH = re.compile(r"(?<!<skill>/)(?<![\w/.])(?:assets|scripts)/[A-Za-z0-9_.-]+\.(?:md|py)")


def read_skill():
    return SKILL_MD.read_text(encoding="utf-8")


def frontmatter(text):
    """{key: value} for the top-level single-line keys of the YAML frontmatter.

    Deliberately not a YAML parser: `index.js` is not one either, and the
    point of this test is to fail on anything it could not read.
    """
    if not text.startswith("---\n"):
        raise AssertionError("SKILL.md must open with a '---' frontmatter fence")
    end = text.index("\n---\n", 3)
    fields = {}
    for line in text[4:end].split("\n"):
        if line.startswith((" ", "\t")) or not line.strip():
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


class DescriptionShapeTest(unittest.TestCase):
    """The frontmatter the harness reads to decide whether to fire."""

    def setUp(self):
        self.text = read_skill()
        self.fields = frontmatter(self.text)

    def test_name_matches_the_skill_folder(self):
        self.assertEqual(self.fields.get("name"), SKILL.name)

    def test_description_is_a_single_line_scalar(self):
        description = self.fields.get("description", "")
        self.assertTrue(description, "description: is missing or empty")
        self.assertNotIn(description[:1], ("|", ">"),
                         "description must be a plain single-line scalar: index.js's "
                         "frontmatter parser cannot read a folded or literal block")
        # A folded scalar also shows up as continuation lines after the key.
        after = self.text.split("description:", 1)[1].split("\n", 1)[1]
        self.assertFalse(after.startswith((" ", "\t")),
                         "description must not be continued on an indented line")

    def test_description_says_when_to_fire_and_when_not_to(self):
        description = self.fields.get("description", "")
        self.assertTrue(description.startswith("Use when "),
                        "description must open with 'Use when ' so the trigger is the first thing read")
        self.assertIn("Not for ", description,
                      "description must say when the skill should NOT fire; without it the "
                      "skill fires on one-file questions and on diagrams unrelated to code")

    def test_description_stays_within_a_readable_length(self):
        length = len(self.fields.get("description", ""))
        self.assertGreater(length, 120, "description is too short to discriminate")
        self.assertLessEqual(length, 1024, f"description is {length} characters; keep it under 1024")


class AssetReferenceTest(unittest.TestCase):
    """Every pointer the agent is told to follow must land on a file."""

    def test_every_referenced_asset_and_script_exists(self):
        text = read_skill()
        referenced = sorted(set(REFERENCE.findall(text)))
        self.assertTrue(referenced, "SKILL.md references no assets or scripts at all")
        missing = [name for name in referenced if not (SKILL / name).is_file()]
        self.assertEqual(missing, [], f"SKILL.md points at files that do not exist: {missing}")

    def test_no_asset_or_script_path_is_written_without_the_skill_prefix(self):
        text = read_skill()
        bare = sorted({m.group(0) for m in BARE_PATH.finditer(text)})
        self.assertEqual(bare, [], "these paths need the <skill>/ prefix; the working directory "
                                   f"is the user's repository, not the skill folder: {bare}")


class WordBudgetTest(unittest.TestCase):
    def test_skill_md_stays_within_its_word_budget(self):
        words = len(read_skill().split())
        self.assertLessEqual(
            words, WORD_BUDGET,
            f"SKILL.md is {words} words against a {WORD_BUDGET}-word budget "
            f"({words - WORD_BUDGET} over). Move reference material into assets/ "
            f"rather than raising the budget.")


if __name__ == "__main__":
    unittest.main()
