"""The labelled prompts that say when architecture-review should and should not fire."""
import json
import re
import unittest

import review_helpers as H


class TriggerPromptsTest(unittest.TestCase):
    def setUp(self):
        self.cases = [json.loads(line) for line in H.TRIGGERS.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_every_case_has_exactly_the_expected_keys(self):
        for case in self.cases:
            self.assertEqual(set(case), {"id", "skill", "prompt", "should_fire", "why"}, case)
            self.assertEqual(case["skill"], "architecture-review")
            self.assertIsInstance(case["should_fire"], bool)

    def test_ids_are_unique(self):
        ids = [c["id"] for c in self.cases]
        self.assertEqual(len(ids), len(set(ids)))

    def test_both_labels_are_covered(self):
        self.assertGreaterEqual(sum(c["should_fire"] for c in self.cases), 3)
        self.assertGreaterEqual(sum(not c["should_fire"] for c in self.cases), 3)

    def test_requests_to_draw_or_document_belong_to_c4_diagrams(self):
        # A review prompt may mention diagrams ("what the diagrams don't show"); it never asks for one.
        for case in self.cases:
            asks_for_output = re.search(r"\b(draw|generate|produce|create|write)\b", case["prompt"].lower())
            if case["should_fire"]:
                self.assertFalse(asks_for_output, case)
        negatives = " ".join(c["prompt"].lower() for c in self.cases if not c["should_fire"])
        self.assertIn("diagram", negatives)
        self.assertIn("documentation", negatives)


if __name__ == "__main__":
    unittest.main()
