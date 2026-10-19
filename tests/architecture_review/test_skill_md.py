"""Lint for skills/architecture-review/SKILL.md, the prompt the agent reads.

The same three failures the c4-diagrams lint guards against: a pointer to a
file that does not exist, a `description:` the harness cannot parse or that
stops saying when not to fire, and unbounded growth (a fixed word budget).
It also holds this skill to its own contract: the description must send
diagram requests to c4-diagrams, and every step the file names must exist.
"""
import re
import unittest

import review_helpers as H

TEXT = (H.SKILL / "SKILL.md").read_text(encoding="utf-8")
WORD_BUDGET = 1200
REFERENCE = re.compile(r"<skill>/((?:assets|scripts|references)/[A-Za-z0-9_.-]+\.(?:md|py))")
BARE_PATH = re.compile(r"(?<!<skill>/)(?<![\w/.])(?:assets|scripts|references)/[A-Za-z0-9_.-]+\.(?:md|py)")


def frontmatter(text):
    """{key: value} for the top-level single-line keys of the YAML frontmatter (not a YAML parser)."""
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


class FrontmatterTest(unittest.TestCase):
    def setUp(self):
        self.fields = frontmatter(TEXT)
        self.description = self.fields.get("description", "")

    def test_name_matches_the_folder(self):
        self.assertEqual(self.fields.get("name"), H.SKILL.name)

    def test_description_is_a_single_line_scalar(self):
        self.assertTrue(self.description)
        self.assertNotIn(self.description[:1], ("|", ">"))
        after = TEXT.split("description:", 1)[1].split("\n", 1)[1]
        self.assertFalse(after.startswith((" ", "\t")), "description must not continue on an indented line")

    def test_description_says_when_to_fire_and_when_not_to(self):
        self.assertTrue(self.description.startswith("Use when "))
        self.assertIn("Not for ", self.description)

    def test_description_length_is_readable(self):
        self.assertGreater(len(self.description), 120)
        self.assertLessEqual(len(self.description), 1024)

    def test_description_sends_diagram_requests_to_c4_diagrams(self):
        self.assertIn("c4-diagrams", self.description)

    def test_version_is_quoted_semver(self):
        self.assertRegex(TEXT, r'(?m)^  version: "\d+\.\d+\.\d+"$')


class ReferenceTest(unittest.TestCase):
    def test_every_referenced_file_exists(self):
        referenced = sorted(set(REFERENCE.findall(TEXT)))
        self.assertTrue(referenced)
        self.assertEqual([r for r in referenced if not (H.SKILL / r).is_file()], [])

    def test_no_path_is_written_without_the_skill_prefix(self):
        self.assertEqual(sorted({m.group(0) for m in BARE_PATH.finditer(TEXT)}), [])

    def test_the_collect_command_matches_the_cli(self):
        self.assertIn('python3 "<skill>/scripts/collect_evidence.py" "<repository_path>"', TEXT)

    def test_the_check_command_matches_the_cli(self):
        self.assertIn('python3 "<skill>/scripts/check_review.py" "<ArchitectureReview.md>" "<repository_path>"', TEXT)
        self.assertIn("Review check: ok", TEXT)

    def test_the_word_budget_holds(self):
        words = len(TEXT.split())
        self.assertLessEqual(words, WORD_BUDGET, f"SKILL.md is {words} words against a {WORD_BUDGET}-word budget")


class FindingContractTest(unittest.TestCase):
    """SKILL.md, the template and the grader must name the same finding fields."""

    def test_skill_md_names_every_graded_field(self):
        from scripts import check_review as grade_review
        for field in grade_review.FIELDS:
            if field != "Lens":  # the template carries Lens; SKILL.md folds it into Evidence
                self.assertIn(f"| {field} |", TEXT, field)

    def test_the_template_has_every_section_the_grader_requires(self):
        from scripts import check_review as grade_review
        template = (H.SKILL / "assets" / "review-report-template.md").read_text(encoding="utf-8")
        for section in grade_review.SECTIONS:
            self.assertIn(f"## {section}", template, section)
        for field in grade_review.FIELDS:
            self.assertIn(f"- **{field}:**", template, field)


if __name__ == "__main__":
    unittest.main()
