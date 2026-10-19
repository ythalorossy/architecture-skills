"""Every fixture file on disk under this suite is tracked by git.

`.gitignore` excludes `docs/` and `audit/` at any depth, so a fixture that
contains a folder with one of those names silently loses it from the commit,
and a test over it keeps passing by finding nothing. Skipped outside a git
checkout.
"""
import subprocess
import unittest
from pathlib import Path

import review_helpers as H

FIXTURES = H.HERE / "fixtures"


def _tracked():
    try:
        done = subprocess.run(
            ["git", "ls-files", "-z", "--", "tests/architecture_review/fixtures"],
            cwd=H.PLUGIN_ROOT, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return {Path(p) for p in done.stdout.split("\0") if p}


class FixturesAreCommittedTest(unittest.TestCase):
    def test_no_fixture_file_is_ignored(self):
        tracked = _tracked()
        if tracked is None:
            self.skipTest("not a git checkout, or git is unavailable")
        on_disk = {p.relative_to(H.PLUGIN_ROOT) for p in FIXTURES.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts}
        missing = sorted(p.as_posix() for p in on_disk - tracked)
        self.assertEqual(missing, [], "fixture files not in the repository:\n  " + "\n  ".join(missing))


if __name__ == "__main__":
    unittest.main()
