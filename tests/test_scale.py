"""
Large monorepos: who owns a file is computed once, and big files are skipped.

On a 20-package npm workspace where each package depends on the previous
one, 95% of the run went to deciding which container and component owned
each evidence line (Path.resolve / is_relative_to per container, component
and line): 18 s for 20 packages, 300 s for 50. It is now about a second.
"""
import contextlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from helpers import run_analyzer, write

from scripts import c4_facts
from scripts.build_graph import build_dependency_graph
from scripts.repo_index import MAX_TEXT_BYTES


def _chain(root, packages, files):
    """Npm workspace: package i depends on package i-1; each file uses pg and an HTTP API."""
    tree = {"package.json": json.dumps({"name": "chain", "private": True, "workspaces": ["packages/*"]})}
    for i in range(packages):
        deps = {"express": "4", "pg": "8", "axios": "1"}
        if i:
            deps[f"@chain/p{i - 1:02}"] = "1.0.0"
        tree[f"packages/p{i:02}/package.json"] = json.dumps(
            {"name": f"@chain/p{i:02}", "version": "1.0.0", "dependencies": deps})
        for j in range(files):
            imports = [f"import {{ x{k} }} from '../m{(j + k) % 4}/f{(j + k) % files}';" for k in (1, 2)]
            if i:
                imports.append(f"import {{ api }} from '@chain/p{i - 1:02}';")
            tree[f"packages/p{i:02}/src/m{j % 4}/f{j}.ts"] = "\n".join(imports + [
                "import { Pool } from 'pg';", "import axios from 'axios';",
                "export const r = axios.get('https://api.payments.example/v1/charges');",
            ]) + "\n"
    write(root, tree)


class ScaleTest(unittest.TestCase):
    def test_thirty_package_chain_is_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "chain"
            _chain(repo, packages=30, files=40)
            start = time.monotonic()
            with contextlib.redirect_stdout(io.StringIO()):
                facts, _ = run_analyzer(repo, Path(tmp) / "out")
            elapsed = time.monotonic() - start
        self.assertEqual(len(facts["containers"]), 30)
        db = next(s for s in facts["data_stores"] if s["name"] == "PostgreSQL")
        self.assertEqual(len(db["used_by"]), 30)
        # About 1 s here; the old code took 47 s on the same machine. Generous for slow CI runners.
        self.assertLess(elapsed, 30, f"analysis took {elapsed:.1f} s")


def _hosts_repo(root, urls, one_line, one_host=False):
    """A Python service whose one module lists `urls` HTTP endpoints, on one line or many.

    With ``one_host`` every URL is a path on the same host, so the scan finds
    thousands of matches and records one external system. That isolates the
    per-match cost, which is what this file is measuring, from the per-result
    cost of recording each new system.
    """
    separator = ", " if one_line else ",\n        "
    template = '"https://api.acmepay.net/p{0}"' if one_host else '"https://s{0}.acmepay.net/p"'
    listed = separator.join(template.format(i) for i in range(urls))
    write(root, {
        "pyproject.toml": '[project]\nname = "shop"\nversion = "1.0"\n',
        "shop/__init__.py": "",
        "shop/hosts.py": (
            "import requests\n"
            "\n"
            "def go():\n"
            "    return requests.get(U[0])\n"
            "\n"
            f"U = [{listed}]\n"
        ),
    })


class SingleLineFileTest(unittest.TestCase):
    """Scanning cost follows a file's size, not the square of its longest line.

    Deciding "is this match inside a string or a comment?" used to re-read the
    line in front of every match, which is linear per match and so quadratic in
    a file written on one line. A 489 KB single-line module took 26 s against
    0.6 s for the same bytes with newlines in them, and a 2 MB one never
    finished. Both scanners now mask the file once instead.
    """

    def test_masking_cost_follows_the_file_count_not_the_match_count(self):
        # The guard that cannot flake: quadrupling the matches in a repository
        # must not change how much masking it does.
        def scan(urls):
            calls = []
            real_mask = c4_facts.code_types.mask

            def counting_mask(text, language, **kwargs):
                calls.append(language)
                return real_mask(text, language, **kwargs)

            with tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp) / "repo"
                _hosts_repo(repo, urls=urls, one_line=True)
                with mock.patch.object(c4_facts.code_types, "mask", counting_mask):
                    facts = c4_facts.collect_facts(repo, build_dependency_graph(repo))
            return len(calls), len(facts["external_systems"])

        few_masks, few_found = scan(500)
        many_masks, many_found = scan(2000)

        # Every URL is still found, on both runs...
        self.assertEqual((few_found, many_found), (500, 2000))
        # ...for the same masking: two modules, each masked for code and for
        # comment-free text, whatever the modules happen to contain.
        self.assertEqual(few_masks, many_masks)
        self.assertEqual(many_masks, 4)

    def test_one_long_line_costs_about_what_the_same_bytes_cost_split(self):
        # Catches the symptom whatever causes it, where the call count above
        # only catches it coming back through the masker. A ratio, not a
        # wall-clock budget: both halves run on this machine, so a slow CI
        # runner moves them together and cannot make this flake.
        timings = {}
        for one_line in (True, False):
            with tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp) / "repo"
                _hosts_repo(repo, urls=10000, one_line=one_line, one_host=True)
                start = time.monotonic()
                facts = c4_facts.collect_facts(repo, build_dependency_graph(repo))
                timings[one_line] = time.monotonic() - start
                self.assertEqual(len(facts["external_systems"]), 1)

        # Floor the divisor: dividing by a near-zero number is its own flake.
        ratio = timings[True] / max(timings[False], 0.05)
        # Measured 0.9 here and 7.8 against the per-match line scans this
        # replaced (10.1 s on one line against 1.3 s for the same bytes split).
        self.assertLess(ratio, 5, f"one line {timings[True]:.2f} s vs split {timings[False]:.2f} s")


class OwnershipTest(unittest.TestCase):
    def test_deepest_component_wins_and_files_nodes_own_only_their_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            write(root, {"app/a.py": "", "app/core/b.py": "", "app/core/deep/c.py": "", "lib/d.py": ""})
            by_id = {
                "app": {"path": root / "app"},
                "app.core": {"path": root / "app" / "core"},
                "app (files)": {"path": root / "app"},
            }
            container = {"id": "svc", "scope": {root / "app"},
                         "components": {"nodes": {"app (files)": {}, "app": {}, "app.core": {}}}}
            owners = c4_facts._Ownership([container], by_id)
            self.assertEqual(owners(root / "app" / "core" / "deep" / "c.py"), [("svc", "app.core")])
            self.assertEqual(owners(root / "app" / "core" / "b.py"), [("svc", "app.core")])
            # app and "app (files)" have the same depth: the first listed wins.
            self.assertEqual(owners(root / "app" / "a.py"), [("svc", "app (files)")])
            self.assertEqual(owners(root / "lib" / "d.py"), [])
            # A sibling folder whose name starts with the scope's is not inside it.
            self.assertEqual(owners(root / "apple" / "x.py"), [])

    def test_large_files_are_not_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            big = Path(tmp) / "bundle.js"
            big.write_bytes(b"import pg from 'pg';\n" + b"x" * MAX_TEXT_BYTES)
            self.assertEqual(c4_facts._file_text(big), "")
            small = Path(tmp) / "small.js"
            small.write_text("import pg from 'pg';\n", encoding="utf-8")
            self.assertIn("pg", c4_facts._file_text(small))


if __name__ == "__main__":
    unittest.main()
