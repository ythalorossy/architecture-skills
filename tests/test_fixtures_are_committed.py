"""Every fixture file on disk is a fixture file in the repository.

`.gitignore` excludes `docs/` and `audit/` — this repository's own working
notes — and those patterns match a folder of that name *at any depth*. A
fixture repository is a small imitation of a real one, so it will sooner or
later contain a folder called `docs`, `build`, `dist`, `out`, `target` or
`coverage`, and git will quietly drop it from the commit.

That failure is invisible in the worst way. The tests over a fixture usually
assert that something is *not* detected, which passes on a fresh clone by
finding no such file at all: the fixture goes on proving nothing, and the
suite stays green. `deploy_lookalike` lost the prose that is half of what it
exists for exactly this way.

Skipped when git is unavailable or this is not a checkout, so running the
suite from a tarball does not fail on something it cannot check.
"""
import subprocess
import unittest
from pathlib import Path

from helpers import REPO_ROOT

FIXTURES = REPO_ROOT / "tests" / "fixtures"


def _tracked():
    """Paths git has, relative to the repository root, or None when it cannot say."""
    try:
        done = subprocess.run(
            ["git", "ls-files", "-z", "--", "tests/fixtures"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return {Path(p) for p in done.stdout.split("\0") if p}


class FixturesAreCommittedTest(unittest.TestCase):
    def setUp(self):
        self.tracked = _tracked()
        if self.tracked is None:
            self.skipTest("not a git checkout, or git is unavailable")

    def test_no_fixture_file_is_ignored(self):
        on_disk = {
            path.relative_to(REPO_ROOT)
            for path in FIXTURES.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }

        missing = sorted(str(p.as_posix()) for p in on_disk - self.tracked)
        self.assertEqual(
            missing, [],
            "these fixture files exist here but are not in the repository, so a "
            "fresh clone and CI run without them:\n  " + "\n  ".join(missing),
        )

    def test_the_check_can_see_the_fixtures_at_all(self):
        # Guards the guard: if ls-files ever returns nothing, the test above
        # would pass by comparing an empty set against an empty set.
        self.assertGreater(len(self.tracked), 50, "git ls-files returned almost nothing")


if __name__ == "__main__":
    unittest.main()
