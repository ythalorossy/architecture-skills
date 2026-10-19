"""Which files the detectors see: what git would commit, never build output."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import review_helpers  # noqa: F401  (puts the skill on sys.path)
from scripts.repo_scan import directory_names, list_files, text_files


def write(root, files):
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class GitAwareListingTest(unittest.TestCase):
    def setUp(self):
        if shutil.which("git") is None:
            self.skipTest("git is not installed")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        write(self.root, {
            ".gitignore": "/.next/\n/out-dir/\n",
            "src/app.ts": "export const a = 1;\n",
            ".next/static/chunk.js": 'const SECRET_TOKEN = "abc123def";\n',
            "out-dir/gen.ts": "x\n",
            "notes/untracked.ts": "y\n",
        })

    def test_gitignored_build_output_is_never_listed(self):
        files = list_files(self.root)
        self.assertIn("src/app.ts", files)
        self.assertFalse([f for f in files if f.startswith((".next/", "out-dir/"))], files)

    def test_untracked_files_git_would_keep_are_listed(self):
        self.assertIn("notes/untracked.ts", list_files(self.root))

    def test_text_files_and_directories_follow_the_same_listing(self):
        self.assertEqual([f.rel for f in text_files(self.root) if f.rel.endswith(".ts")], ["notes/untracked.ts", "src/app.ts"])
        self.assertNotIn("out-dir", directory_names(self.root))


class FallbackListingTest(unittest.TestCase):
    def test_outside_git_the_known_build_folders_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, {"src/a.ts": "x\n", ".next/b.js": "y\n", "node_modules/c/d.js": "z\n",
                         "architecture-docs/r/e.json": "{}"})
            self.assertEqual(list_files(root), ["src/a.ts"])


if __name__ == "__main__":
    unittest.main()
