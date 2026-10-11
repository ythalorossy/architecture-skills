"""
Secrets never reach the generated files.

ArchitectureReport.md and c4-facts.json are meant to be committed and
shared, so a password must not be copied into them, whether it sits in a
secret-named variable (POSTGRES_PASSWORD) or inside a URL or connection
string held by an innocent-looking one (DATABASE_URL).
"""
import tempfile
import unittest
from pathlib import Path

from helpers import run_analyzer

from scripts.code_facts import redact_value

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "repos"


class RedactValueTest(unittest.TestCase):
    def test_url_passwords_are_masked(self):
        cases = {
            "postgresql://bookshop:bookshop@db:5432/bookshop": "postgresql://bookshop:***@db:5432/bookshop",
            "jdbc:postgresql://app:s3cr3t@db/orders": "jdbc:postgresql://app:***@db/orders",
            "mongodb+srv://svc:p%40ss@cluster0.example.net/app": "mongodb+srv://svc:***@cluster0.example.net/app",
            "redis://:hunter2@cache:6379/0": "redis://:***@cache:6379/0",
            "amqp://guest:guest@rabbit:5672/": "amqp://guest:***@rabbit:5672/",
        }
        for value, expected in cases.items():
            self.assertEqual(redact_value(value), expected)

    def test_connection_string_passwords_are_masked(self):
        self.assertEqual(redact_value("Server=db;Database=app;User Id=sa;Password=Pa55w0rd;"),
                         "Server=db;Database=app;User Id=sa;Password=***;")
        self.assertEqual(redact_value("host=db user=app pwd=x1"), "host=db user=app pwd=***")

    def test_values_without_secrets_are_unchanged(self):
        for value in ("http://api:8000", "https://user@example.com/repo.git", "8080",
                      "https://api.example.com/v1?page=2", "db:5432", ""):
            self.assertEqual(redact_value(value), value)


class GeneratedFilesTest(unittest.TestCase):
    def assert_no_secret(self, fixture, secrets, masked):
        with tempfile.TemporaryDirectory() as tmp:
            run_analyzer(FIXTURES / fixture, tmp)
            for name in ("ArchitectureReport.md", "c4-facts.json"):
                text = (Path(tmp) / name).read_text(encoding="utf-8")
                for secret in secrets:
                    self.assertNotIn(secret, text, f"{fixture}/{name}")
                self.assertIn(masked, text, f"{fixture}/{name}")

    def test_compose_credentials_are_not_copied(self):
        # docker-compose.yml: POSTGRES_PASSWORD: acme, DATABASE_URL with acme:acme@
        self.assert_no_secret("compose_poly", ["acme:acme@", '"POSTGRES_PASSWORD": "acme"'],
                              "postgresql://acme:***@db:5432/acme")
        self.assert_no_secret("bookshop", ["bookshop:bookshop@", '"POSTGRES_PASSWORD": "bookshop"'],
                              "postgresql://bookshop:***@db:5432/bookshop")


if __name__ == "__main__":
    unittest.main()
