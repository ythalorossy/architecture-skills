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

from helpers import run_analyzer, write

from scripts import c4_facts


def _chain(root, packages, files):
    """npm workspace: package i depends on package i-1; each file uses pg and an HTTP API."""
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
            big.write_bytes(b"import pg from 'pg';\n" + b"x" * c4_facts.MAX_TEXT_BYTES)
            self.assertEqual(c4_facts._file_text(big), "")
            small = Path(tmp) / "small.js"
            small.write_text("import pg from 'pg';\n", encoding="utf-8")
            self.assertIn("pg", c4_facts._file_text(small))


if __name__ == "__main__":
    unittest.main()
