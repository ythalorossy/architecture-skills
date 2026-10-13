"""Comments and string literals are recognised the same way everywhere.

The signal and URL scanners used to decide "is this match inside a string?"
and "is this match inside a comment?" by counting quotes and looking for a
``#`` on the line in front of the match. Both answers are wrong as soon as
the line holds a string: an apostrophe inside one makes the quote count
odd, and a ``#`` or ``//`` inside one looks exactly like a comment marker.

A dependency that is real must be found whatever else shares its line, and
a name that only appears in prose or in a doc comment must not be reported
as a dependency.
"""
import tempfile
import unittest
from pathlib import Path

from helpers import write

from scripts.build_graph import build_dependency_graph
from scripts.c4_facts import collect_facts


def _facts(files):
    """collect_facts over a throwaway repo built from {relative path: text}."""
    with tempfile.TemporaryDirectory() as tmp:
        # Resolved: on Windows mkdtemp returns the 8.3 short form, which does
        # not compare with the long form the index stores.
        root = Path(tmp).resolve()
        write(root, files)
        return collect_facts(root, build_dependency_graph(root))


def _technologies(facts, key):
    return sorted(entry["technology"] for entry in facts[key])


def _names(facts, key):
    return sorted(entry["name"] for entry in facts[key])


class StringLiteralTest(unittest.TestCase):
    """A string on the line must not hide the code next to it."""

    def test_an_apostrophe_in_a_string_does_not_hide_a_real_store(self):
        # Quote counting sees one ' in `"it's fine"` and calls the rest of
        # the line a string, so the RedisTemplate beside it is dropped.
        facts = _facts({
            "pom.xml": _POM,
            "src/main/java/com/acme/Cache.java": (
                "package com.acme;\n"
                "public class Cache {\n"
                '  String msg = "it\'s fine"; RedisTemplate<String, String> t = null;\n'
                "}\n"
            ),
        })

        self.assertIn("Redis", _technologies(facts, "data_stores"))

    def test_a_name_inside_a_block_comment_is_not_a_store(self):
        facts = _facts({
            "pom.xml": _POM,
            "src/main/java/com/acme/Notes.java": (
                "package com.acme;\n"
                "/*\n"
                " * We removed the RedisTemplate in 2019.\n"
                " */\n"
                "public class Notes {}\n"
            ),
        })

        self.assertNotIn("Redis", _technologies(facts, "data_stores"))

    def test_a_name_inside_a_docstring_is_not_a_store(self):
        # The second line of a triple-quoted string has nothing in front of
        # it, so counting quotes on that line alone finds none.
        facts = _facts({
            "pyproject.toml": _PYPROJECT,
            "shop/__init__.py": "",
            "shop/notes.py": (
                '"""Design notes.\n'
                "\n"
                "MongoTemplate was considered and rejected.\n"
                '"""\n'
            ),
        })

        self.assertNotIn("MongoDB", _technologies(facts, "data_stores"))


class CommentMarkerTest(unittest.TestCase):
    """A ``#`` or ``//`` inside a string is not a comment."""

    def test_a_hash_in_a_string_does_not_hide_a_real_url(self):
        facts = _facts({
            "pyproject.toml": _PYPROJECT,
            "shop/__init__.py": "",
            "shop/client.py": (
                "import requests\n"
                "def get():\n    return requests.get(URL)\n"
                'TAG = "#release"; URL = "https://payments.acmepay.net/v1"\n'
            ),
        })

        self.assertIn("payments.acmepay.net", _names(facts, "external_systems"))

    def test_a_double_slash_in_a_string_does_not_hide_a_real_url(self):
        facts = _facts({
            "package.json": _PACKAGE_JSON,
            "src/client.js": (
                "const axios = require('axios');\n"
                'const SEP = "//"; const URL = "https://payments.acmepay.net/v1";\n'
            ),
        })

        self.assertIn("payments.acmepay.net", _names(facts, "external_systems"))

    def test_a_url_in_a_comment_is_still_ignored(self):
        # The behaviour the two helpers were there to provide, kept.
        facts = _facts({
            "pyproject.toml": _PYPROJECT,
            "shop/__init__.py": "",
            "shop/client.py": (
                "import requests\n"
                "def get():\n    return requests.get(URL)\n"
                "# see https://payments.acmepay.net/v1 for the contract\n"
            ),
        })

        self.assertNotIn("payments.acmepay.net", _names(facts, "external_systems"))

    def test_a_url_in_a_string_is_still_found(self):
        # URLs live in string literals. Masking string *contents* for the URL
        # scan would delete every external system the skill detects.
        facts = _facts({
            "pyproject.toml": _PYPROJECT,
            "shop/__init__.py": "",
            "shop/client.py": (
                "import requests\n"
                "def get():\n    return requests.get(URL)\n"
                'URL = "https://payments.acmepay.net/v1"\n'
            ),
        })

        self.assertIn("payments.acmepay.net", _names(facts, "external_systems"))


class UnknownLanguageTest(unittest.TestCase):
    """A suffix the masker has no rules for keeps today's behaviour."""

    def test_a_vue_file_still_contributes_its_url(self):
        facts = _facts({
            "package.json": _PACKAGE_JSON,
            "src/App.vue": (
                "<script>\n"
                "import axios from 'axios';\n"
                "const URL = 'https://payments.acmepay.net/v1';\n"
                "</script>\n"
            ),
        })

        self.assertIn("payments.acmepay.net", _names(facts, "external_systems"))


_POM = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
    "  <modelVersion>4.0.0</modelVersion>\n"
    "  <groupId>com.acme</groupId>\n"
    "  <artifactId>cache</artifactId>\n"
    "  <version>1.0</version>\n"
    "</project>\n"
)

_PYPROJECT = (
    "[project]\n"
    'name = "shop"\n'
    'version = "1.0"\n'
)

_PACKAGE_JSON = '{\n  "name": "shop",\n  "version": "1.0.0"\n}\n'


if __name__ == "__main__":
    unittest.main()
