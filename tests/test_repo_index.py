"""
Tests for RepoIndex — SPEC-03 Tasks 1-3.

These tests cover:
- Task 1: single walk, ignore policy, views
- Task 2: tolerant walk (REL-02) — permission errors, symlinks
- Task 3: tolerant reader (REL-01) — encoding, cap, structured readers
"""
import os
import stat
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
SKILL_SCRIPTS = REPO / "skills" / "c4-diagrams" / "scripts"


class _ImportRepoIndex:
    """Import RepoIndex with fallback for pre-existence check."""

    @staticmethod
    def _find():
        """Find repo_index module path if it exists."""
        repo_index = SKILL_SCRIPTS / "repo_index.py"
        if not repo_index.exists():
            return None
        import sys
        if str(SKILL_SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SKILL_SCRIPTS))
        from repo_index import RepoIndex
        return RepoIndex

    def __call__(self):
        return self._find()


def _repo_index():
    """Import RepoIndex or return None if not yet implemented."""
    return _ImportRepoIndex()._find()


class _MockCollector:
    """Minimal SPEC-08 collector stub for tests."""

    def __init__(self):
        self.warnings = []
        self._skipped_list = []

    def skipped(self, path, reason):
        """Record a skipped path (SPEC-08 collector interface)."""
        self._skipped_list.append({"path": str(path), "reason": reason})

    @property
    def skipped_entries(self):
        """Access the list of skipped entries for assertions."""
        return self._skipped_list

    def warn(self, kind, file=None, detail=None):
        self.warnings.append({"kind": kind, "file": file, "detail": detail})


# ---------------------------------------------------------------------------
# Task 1: ignore policy
# ---------------------------------------------------------------------------

class TestIgnorePolicy(unittest.TestCase):
    """Base ignore set, pyvenv.cfg, dot-folder allowlist."""

    def test_node_modules_is_ignored(self):
        RepoIndex = _repo_index()
        if RepoIndex is None:
            self.skipTest("repo_index.py not yet implemented")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "node_modules" / "pkg").mkdir(parents=True)
            (repo / "node_modules" / "pkg" / "index.js").write_text("")
            collector = _MockCollector()
            index = RepoIndex.build(repo, collector)
            files = list(index.files("all"))
            self.assertEqual(files, [], "node_modules must be pruned from walk")

    def test_venv_is_ignored(self):
        RepoIndex = _repo_index()
        if RepoIndex is None:
            self.skipTest("repo_index.py not yet implemented")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            venv = repo / ".venv"
            venv.mkdir()
            (venv / "pyvenv.cfg").write_text("")
            (repo / "good.py").write_text("")
            collector = _MockCollector()
            index = RepoIndex.build(repo, collector)
            names = {f.name for f in index.files("all")}
            self.assertIn("good.py", names)
            self.assertNotIn(".venv", names)

    def test_pyvenv_cfg_folder_is_ignored(self):
        RepoIndex = _repo_index()
        if RepoIndex is None:
            self.skipTest("repo_index.py not yet implemented")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            # A folder that is NOT named .venv but contains pyvenv.cfg
            weird_venv = repo / "myenv"
            weird_venv.mkdir()
            (weird_venv / "pyvenv.cfg").write_text("")
            (repo / "good.py").write_text("")
            collector = _MockCollector()
            index = RepoIndex.build(repo, collector)
            names = {f.name for f in index.files("all")}
            self.assertIn("good.py", names)
            self.assertNotIn("myenv", names)

    def test_dot_allowlist_keeps_github_and_gitlab_ci(self):
        RepoIndex = _repo_index()
        if RepoIndex is None:
            self.skipTest("repo_index.py not yet implemented")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / ".github" / "workflows" / "ci.yml").parent.mkdir(parents=True)
            (repo / ".github" / "workflows" / "ci.yml").write_text("runs-on: ubuntu")
            (repo / ".gitlab-ci.yml").write_text("image: python")
            (repo / ".git" / "config").parent.mkdir(parents=True)
            (repo / ".git" / "config").write_text("")
            (repo / ".venv" / "pyvenv.cfg").parent.mkdir(parents=True)
            (repo / ".venv" / "pyvenv.cfg").write_text("")
            collector = _MockCollector()
            index = RepoIndex.build(repo, collector)
            names = {f.name for f in index.files("all")}
            # Allowed dot-folders
            self.assertIn("ci.yml", names)
            self.assertIn(".gitlab-ci.yml", names)
            # Disallowed dot-folders
            self.assertNotIn("config", names)  # .git/config
            self.assertNotIn("pyvenv.cfg", names)  # .venv/pyvenv.cfg

    def test_order_is_sorted_and_deterministic(self):
        RepoIndex = _repo_index()
        if RepoIndex is None:
            self.skipTest("repo_index.py not yet implemented")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            for name in ["z.py", "a.py", "m.py"]:
                (repo / name).write_text("")
            collector = _MockCollector()
            index = RepoIndex.build(repo, collector)
            names = [f.name for f in index.files("all")]
            self.assertEqual(names, sorted(names), "files must be sorted")


# ---------------------------------------------------------------------------
# Task 2: tolerant walk — REL-02
# ---------------------------------------------------------------------------

class TestTolerantWalk(unittest.TestCase):
    """Permission errors and symlinks are skipped, not raised."""

    @unittest.skipUnless(os.name == "posix", "POSIX-only: chmod 000")
    def test_unreadable_dir_skipped_with_reason_permission(self):
        RepoIndex = _repo_index()
        if RepoIndex is None:
            self.skipTest("repo_index.py not yet implemented")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            unreadable = repo / "no_access"
            unreadable.mkdir()
            (unreadable / "secret.py").write_text("")
            (repo / "good.py").write_text("")
            os.chmod(unreadable, 0)
            try:
                collector = _MockCollector()
                index = RepoIndex.build(repo, collector)
                files = list(index.files("all"))
                names = {f.name for f in files}
                self.assertIn("good.py", names)
                self.assertNotIn("secret.py", names)
                self.assertTrue(
                    any("no_access" in s["path"] for s in collector.skipped_entries),
                    f"'no_access' must be in skipped_paths; got {collector.skipped_entries}"
                )
                reasons = [s["reason"] for s in collector.skipped_entries if "no_access" in s["path"]]
                self.assertEqual(reasons, ["permission"], "reason must be 'permission'")
            finally:
                os.chmod(unreadable, 0o755)

    @unittest.skipUnless(os.name == "posix", "POSIX-only: symlinks")
    def test_outside_symlink_skipped(self):
        RepoIndex = _repo_index()
        if RepoIndex is None:
            self.skipTest("repo_index.py not yet implemented")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            outside = Path(tmp) / "outside"
            outside.mkdir()
            (outside / "leak.py").write_text("y = 2\n")
            link = repo / "leak"
            link.symlink_to(outside / "leak.py")
            (repo / "good.py").write_text("")
            collector = _MockCollector()
            index = RepoIndex.build(repo, collector)
            names = {f.name for f in index.files("all")}
            self.assertIn("good.py", names)
            self.assertNotIn("leak.py", names)
            self.assertTrue(link.is_symlink(), "leak must still be a symlink in repo")
            skip_paths = [s["path"] for s in collector.skipped_entries]
            self.assertTrue(
                any("leak" in p for p in skip_paths),
                f"leak symlink must be in skipped_files; got {skip_paths}",
            )
            reasons = [s["reason"] for s in collector.skipped_entries if "leak" in s["path"]]
            self.assertEqual(reasons, ["outside_symlink"], "reason must be 'outside_symlink'")

    @unittest.skipUnless(os.name == "posix", "POSIX-only: symlinks")
    def test_dangling_absolute_symlink_skipped(self):
        RepoIndex = _repo_index()
        if RepoIndex is None:
            self.skipTest("repo_index.py not yet implemented")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            dangling = repo / "missing.csproj"
            dangling.symlink_to("/nonexistent/path/file.csproj")
            (repo / "good.py").write_text("")
            collector = _MockCollector()
            index = RepoIndex.build(repo, collector)
            names = {f.name for f in index.files("all")}
            self.assertIn("good.py", names)
            self.assertNotIn("missing.csproj", names)
            skip_paths = [s["path"] for s in collector.skipped_entries]
            self.assertTrue(
                any("missing.csproj" in p for p in skip_paths),
                f"dangling symlink must be in skipped_files; got {skip_paths}",
            )
            reasons = [s["reason"] for s in collector.skipped_entries if "missing.csproj" in s["path"]]
            self.assertEqual(reasons, ["broken_symlink"], "reason must be 'broken_symlink'")

    def test_each_skip_recorded_once(self):
        RepoIndex = _repo_index()
        if RepoIndex is None:
            self.skipTest("repo_index.py not yet implemented")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            unreadable = repo / "no_access"
            unreadable.mkdir()
            (unreadable / "file.py").write_text("")
            os.chmod(unreadable, 0)
            try:
                collector = _MockCollector()
                index = RepoIndex.build(repo, collector)
                # Access files multiple times through different views
                list(index.files("all"))
                list(index.files("source"))
                list(index.by_suffix(".py"))
                skip_paths = [s["path"] for s in collector.skipped_entries]
                no_access_count = sum(1 for p in skip_paths if "no_access" in p)
                self.assertEqual(
                    no_access_count, 1,
                    f"no_access must be skipped exactly once; got {no_access_count} times: {skip_paths}",
                )
            finally:
                os.chmod(unreadable, 0o755)


# ---------------------------------------------------------------------------
# Task 3: tolerant reader — REL-01
# ---------------------------------------------------------------------------

class TestTolerantReader(unittest.TestCase):
    """read_text, structured readers, cache, cap enforcement."""

    def test_read_text_latin1_replaced_and_warned(self):
        RepoIndex = _repo_index()
        if RepoIndex is None:
            self.skipTest("repo_index.py not yet implemented")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            latin1_file = repo / "latin1.cfg"
            latin1_file.write_bytes(b"name = b\xff\xfenomer\n")
            collector = _MockCollector()
            index = RepoIndex.build(repo, collector)
            text = index.read_text(latin1_file)
            self.assertIsNotNone(text, "read_text must return text, not None for Latin-1")
            self.assertIn("�", text, "replacement char must appear for invalid UTF-8 bytes")
            parse_warnings = [w for w in collector.warnings if w["kind"] == "parse"]
            self.assertEqual(len(parse_warnings), 1, "exactly one parse warning must be recorded")
            self.assertIn("latin1.cfg", parse_warnings[0]["file"], "warning must name the file")

    def test_read_text_oserror_returns_none(self):
        RepoIndex = _repo_index()
        if RepoIndex is None:
            self.skipTest("repo_index.py not yet implemented")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            missing = repo / "missing.txt"
            collector = _MockCollector()
            index = RepoIndex.build(repo, collector)
            text = index.read_text(missing)
            self.assertIsNone(text, "read_text must return None for missing file")

    @unittest.skipUnless(os.name == "posix", "POSIX-only: chmod 000")
    def test_read_text_permission_error_returns_none(self):
        RepoIndex = _repo_index()
        if RepoIndex is None:
            self.skipTest("repo_index.py not yet implemented")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            secret = repo / "secret.txt"
            secret.write_text("hidden")
            os.chmod(secret, 0)
            try:
                collector = _MockCollector()
                index = RepoIndex.build(repo, collector)
                text = index.read_text(secret)
                self.assertIsNone(text, "read_text must return None for unreadable file")
            finally:
                os.chmod(secret, 0o644)

    def test_read_cached_once_per_file(self):
        RepoIndex = _repo_index()
        if RepoIndex is None:
            self.skipTest("repo_index.py not yet implemented")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "a.txt").write_text("content-a")
            (repo / "b.txt").write_text("content-b")
            collector = _MockCollector()
            index = RepoIndex.build(repo, collector)
            # Read the same file multiple times
            text1 = index.read_text(repo / "a.txt")
            text2 = index.read_text(repo / "a.txt")
            text3 = index.read_text(repo / "a.txt")
            self.assertEqual(text1, text2)
            self.assertEqual(text2, text3)
            # Different files are different
            self.assertNotEqual(text1, index.read_text(repo / "b.txt"))

    def test_file_over_cap_not_read_and_skipped_too_large(self):
        RepoIndex = _repo_index()
        if RepoIndex is None:
            self.skipTest("repo_index.py not yet implemented")
        # Find the cap constant
        from repo_index import MAX_TEXT_BYTES
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            big = repo / "big.txt"
            big.write_bytes(b"x" * (MAX_TEXT_BYTES + 1))
            collector = _MockCollector()
            index = RepoIndex.build(repo, collector)
            text = index.read_text(big)
            self.assertIsNone(text, "read_text must return None for files over cap")
            too_large = [s for s in collector.skipped_entries if s["reason"] == "too_large"]
            self.assertEqual(len(too_large), 1, "exactly one skip with reason 'too_large'")
            self.assertIn("big.txt", too_large[0]["path"])

    def test_read_toml_invalid_returns_none_with_warning(self):
        RepoIndex = _repo_index()
        if RepoIndex is None:
            self.skipTest("repo_index.py not yet implemented")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            bad_toml = repo / "pyproject.toml"
            bad_toml.write_text("[project\ngarbage")
            collector = _MockCollector()
            index = RepoIndex.build(repo, collector)
            data = index.read_toml(bad_toml)
            self.assertIsNone(data, "read_toml must return None for invalid TOML")
            parse_warnings = [w for w in collector.warnings if w["kind"] == "parse"]
            self.assertEqual(len(parse_warnings), 1)
            self.assertIn("pyproject.toml", parse_warnings[0]["file"])

    def test_parse_xml_permission_error_returns_none(self):
        RepoIndex = _repo_index()
        if RepoIndex is None:
            self.skipTest("repo_index.py not yet implemented")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            xml_file = repo / "test.csproj"
            xml_file.write_text("<Project><ItemGroup/></Project>")
            os.chmod(xml_file, 0)
            try:
                collector = _MockCollector()
                index = RepoIndex.build(repo, collector)
                result = index.parse_xml(xml_file)
                self.assertIsNone(result, "parse_xml must return None on permission error")
            finally:
                os.chmod(xml_file, 0o644)

    def test_read_ini_invalid_returns_none(self):
        RepoIndex = _repo_index()
        if RepoIndex is None:
            self.skipTest("repo_index.py not yet implemented")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            bad_ini = repo / "setup.cfg"
            bad_ini.write_text("[metadata\nname = bad ini")
            collector = _MockCollector()
            index = RepoIndex.build(repo, collector)
            data = index.read_ini(bad_ini)
            self.assertIsNone(data, "read_ini must return None for invalid INI")


if __name__ == "__main__":
    unittest.main()
