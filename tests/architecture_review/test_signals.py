"""Each detector in scripts/signals.py: what it flags, and what it must leave alone."""
import json
import tempfile
import unittest
from pathlib import Path

import review_helpers  # noqa: F401  (puts the skill on sys.path)
from scripts import signals as S
from scripts.repo_scan import directory_names, text_files


def run(detector, files, facts=None):
    """Write `files` ({relative path: text}) to a temp repo and run one detector on it."""
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    ctx = S.Context(root, facts or {}, text_files(root), directory_names(root))
    try:
        return detector(ctx)
    finally:
        tmp.cleanup()


def kinds(found):
    return [s.kind for s in found]


class SecretDefaultTest(unittest.TestCase):
    def test_flags_a_secret_named_env_default(self):
        found = run(S.detect_secret_defaults, {
            "app/settings.py": 'import os\nSECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret")\n'})
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].detail["variable"], "SECRET_KEY")
        self.assertEqual(found[0].locations, ("app/settings.py:2",))

    def test_flags_a_default_split_over_lines(self):
        found = run(S.detect_secret_defaults, {
            "s.py": 'import os\nJWT_SECRET = os.getenv(\n    "JWT_SECRET", "devsecret123"\n)\n'})
        self.assertEqual([s.detail["variable"] for s in found], ["JWT_SECRET"])

    def test_leaves_a_non_secret_default_alone(self):
        found = run(S.detect_secret_defaults, {
            "s.py": 'import os\nLOG_LEVEL = os.environ.get("LOG_LEVEL", "info")\n'
                    'ENV = os.getenv("APP_ENV", "development")\n'})
        self.assertEqual(found, [])

    def test_flags_a_javascript_default_and_a_spring_default(self):
        js = run(S.detect_secret_defaults, {"a.js": 'const k = process.env.API_KEY || "abcd1234";\n'})
        spring = run(S.detect_secret_defaults, {"application.yml": "db:\n  password: ${DB_PASSWORD:admin123}\n"})
        self.assertEqual([s.detail["variable"] for s in js], ["API_KEY"])
        self.assertEqual([s.detail["variable"] for s in spring], ["DB_PASSWORD"])

    def test_flags_a_literal_assignment_but_not_a_name_reference(self):
        found = run(S.detect_secret_defaults, {
            "c.py": 'API_TOKEN = "tok_live_12345"\nTOKEN_KEY = "AUTH_TOKEN"\npassword_label = "Enter your password"\n'})
        self.assertEqual([s.detail["variable"] for s in found], ["API_TOKEN"])

    def test_ignores_templating_and_test_files(self):
        found = run(S.detect_secret_defaults, {
            "c.py": 'import os\nX = os.environ.get("DB_PASSWORD", "${VAULT_PASSWORD}")\n',
            "tests/test_c.py": 'SECRET_KEY = "only-in-a-test"\n'})
        self.assertEqual(found, [])

    def test_never_carries_the_value(self):
        found = run(S.detect_secret_defaults, {"s.py": 'SECRET_KEY = "hunter2-very-secret"\n'})
        self.assertNotIn("hunter2", json.dumps([s.to_dict("x") for s in found]))


class ConfigSecretTest(unittest.TestCase):
    """Secrets set in config files, in each format a repository commits them in."""

    def variables(self, files):
        return [s.detail["variable"] for s in run(S.detect_secret_defaults, files)]

    def test_a_nested_json_setting_is_named_by_its_path(self):
        found = run(S.detect_secret_defaults, {"appsettings.json": '{\n  "ApiCredentials": {\n    "key": "k-81f2a9",\n'
                                                                    '    "value": "v-77cc1e2b"\n  }\n}\n'})
        self.assertEqual([s.detail["variable"] for s in found], ["APICREDENTIALS.KEY", "APICREDENTIALS.VALUE"])
        self.assertEqual(found[1].locations, ("appsettings.json:4",))
        self.assertEqual(found[0].detail["forms"], ["config"])

    def test_json_with_comments_falls_back_to_a_pattern(self):
        text = '{\n  // dev only\n  "Password": "hunter2-dev"\n}\n'
        self.assertEqual(self.variables({"appsettings.json": text}), ["PASSWORD"])

    def test_settings_repeated_per_entry_are_one_signal(self):
        text = ('{"Carriers": {"Kaiser": {"password": "p-1aa9f3"}, "Moda": {"password": "p-2bb8e4"}}}')
        found = run(S.detect_secret_defaults, {"appsettings.json": text})
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].detail["variable"], "CARRIERS.*.PASSWORD")
        self.assertEqual(found[0].detail["settings"], ["CARRIERS.KAISER.PASSWORD", "CARRIERS.MODA.PASSWORD"])

    def test_an_npmrc_auth_token_is_flagged(self):
        text = "@fortawesome:registry=https://npm.fontawesome.com/\n//npm.fontawesome.com/:_authToken=0A1B-2C3D-4E5F\n"
        found = run(S.detect_secret_defaults, {"public/.npmrc": text})
        self.assertEqual([s.detail["variable"] for s in found], ["_AUTHTOKEN"])
        self.assertEqual(found[0].locations, ("public/.npmrc:2",))

    def test_yaml_ini_env_and_xml_settings_are_flagged(self):
        self.assertEqual(self.variables({"config.yml": "db:\n  password: s3cr3t-value\n"}), ["PASSWORD"])
        self.assertEqual(self.variables({"app.ini": "[db]\napi_key = k3y-value-9\n"}), ["API_KEY"])
        self.assertEqual(self.variables({".env.production": "export JWT_SECRET=abc123xyz\n"}), ["JWT_SECRET"])
        self.assertEqual(self.variables({"web.config": '<add key="ApiToken" value="t0ken-value-1"/>'}), ["APITOKEN"])

    def test_values_that_are_not_secrets_are_left_alone(self):
        text = ('{"RequirePassword": "true", "TokenEndpoint": "https://login.example/token",'
                ' "PasswordLabel": "Password", "TokenTtl": "3600"}')
        self.assertEqual(self.variables({"appsettings.json": text}), [])

    def test_lexer_constants_and_fetch_options_are_left_alone(self):
        text = 'const COLOR_TOKEN = "color";\nconst VAR_FUNCTION_TOKEN = "var(";\nconst CREDENTIALS = "same-origin";\n'
        self.assertEqual(self.variables({"lexer.js": text}), [])

    def test_an_uppercase_hex_key_is_a_secret_not_a_variable_name(self):
        # The .NET miss: 32-character uppercase hex keys were dropped as if they named an env var.
        text = '{"ApiCredentials": {"key": "3F9A0C1B7E2D4F6A8B9C0D1E2F3A4B5C", "value": "AUTH_TOKEN"}}'
        found = run(S.detect_secret_defaults, {"appsettings.json": text})
        self.assertEqual([s.detail["variable"] for s in found], ["APICREDENTIALS.KEY"])  # AUTH_TOKEN names a var

    def test_placeholders_are_not_secrets(self):
        text = '{"ApiKey": "your-api-key-here", "Token": "xxxxxxxx", "Secret": "placeholder-value", "Pwd": "[PASSWORD]"}'
        self.assertEqual(self.variables({"appsettings.json": text}), [])

    def test_a_commented_out_setting_is_not_live(self):
        text = 'import os\n# SECRET_KEY = "old-dev-secret-1"\n// API_TOKEN = "tok_9f8e7d6c"\n'
        self.assertEqual(self.variables({"settings.py": text}), [])

    def test_lockfiles_are_not_read(self):
        self.assertEqual(self.variables({"package-lock.json": '{"token": "abc123def456"}'}), [])


class CredentialsInUrlTest(unittest.TestCase):
    def test_flags_a_password_in_compose_and_source(self):
        found = run(S.detect_credentials_in_urls, {
            "docker-compose.yml": "services:\n  api:\n    environment:\n      - DB=postgres://u:s3cr3tpw@db/x\n",
            "app.py": 'URL = "redis://cache:p4ssw0rd1@host/0"\n'})
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].locations, ("app.py:1", "docker-compose.yml:4"))
        self.assertEqual(found[0].confidence, "high")

    def test_ignores_templated_and_masked_passwords(self):
        found = run(S.detect_credentials_in_urls, {
            "a.yml": "x: postgres://u:${DB_PASS}@db/x\ny: postgres://u:***@db/x\nz: amqp://u:{{ pw }}@h\n"})
        self.assertEqual(found, [])

    def test_a_key_value_connection_string_is_flagged(self):
        text = ('{"ConnectionStrings": {"Plans": "Host=db.example;Database=plans;Username=app;Password=Pg-9f8e7d;"}}\n')
        found = run(S.detect_credentials_in_urls, {"appsettings.json": text})
        self.assertEqual(found[0].detail["schemes"], ["key=value"])
        self.assertEqual(found[0].locations, ("appsettings.json:1",))

    def test_key_value_without_a_password_or_with_a_placeholder_is_fine(self):
        text = ('Server=sql.example;Database=plans;Integrated Security=true;\n'
                'Server=sql.example;User Id=app;Password=${DB_PASSWORD};\n')
        self.assertEqual(run(S.detect_credentials_in_urls, {"a.config": text}), [])

    def test_placeholder_and_commented_out_connection_strings_are_fine(self):
        text = ('{"Db": "Host=localhost;Database=x;Username=u;Password=[YOURPASSWORD];"}\n'
                '// var cs = "Server=10.0.0.5;User Id=sa;Password=Dev-9f8e7d;";\n'
                '# url = postgres://u:R3al-pw-77@db/x\n')
        self.assertEqual(run(S.detect_credentials_in_urls, {"a.json": text.split("\n")[0], "Ctx.cs": text.split("\n")[1],
                                                            "b.ini": text.split("\n")[2]}), [])

    def test_a_password_line_that_is_not_a_connection_string_is_not_this_detector(self):
        self.assertEqual(run(S.detect_credentials_in_urls, {"app.ini": "password=abc123xyz\n"}), [])

    def test_a_placeholder_password_is_low_confidence(self):
        found = run(S.detect_credentials_in_urls, {"a.yml": "x: postgres://user:password@db/x\n"})
        self.assertEqual(found[0].confidence, "low")


class AuthMarkersTest(unittest.TestCase):
    FACTS = {
        "containers": [{"id": "api", "path": "api"}],
        "endpoints": [{"method": "GET", "path": "/items", "file": "api/app.py", "line": 7, "container": "api"}],
    }

    def test_flags_endpoints_with_no_marker(self):
        found = run(S.detect_auth_markers_absent, {"api/app.py": "def items(): ...\n"}, self.FACTS)
        self.assertEqual(kinds(found), ["auth-markers-absent"])
        self.assertEqual(found[0].confidence, "low")
        self.assertEqual(found[0].detail["sample"], ["GET /items"])

    def test_every_file_that_defines_endpoints_is_a_location(self):
        facts = {"containers": [{"id": "api", "path": "api"}], "endpoints": [
            {"method": "GET", "path": "/a", "file": "api/A.py", "line": 3, "container": "api"},
            {"method": "GET", "path": "/b", "file": "api/A.py", "line": 9, "container": "api"},
            {"method": "GET", "path": "/c", "file": "api/B.py", "line": 4, "container": "api"}]}
        found = run(S.detect_auth_markers_absent, {"api/A.py": "x = 1\n", "api/B.py": "y = 2\n"}, facts)
        self.assertEqual(found[0].locations, ("api/A.py:3", "api/B.py:4"))  # first endpoint of each file

    def test_a_marker_anywhere_in_the_container_clears_it(self):
        found = run(S.detect_auth_markers_absent, {
            "api/app.py": "def items(): ...\n", "api/deps.py": "def f(user=Depends(get_current_user)): ...\n"},
            self.FACTS)
        self.assertEqual(found, [])

    def test_a_container_without_endpoints_is_skipped(self):
        facts = {"containers": [{"id": "worker", "path": "worker"}], "endpoints": []}
        self.assertEqual(run(S.detect_auth_markers_absent, {"worker/t.py": "x = 1\n"}, facts), [])


class PublishedPortTest(unittest.TestCase):
    COMPOSE = "services:\n  db:\n    image: postgres:16\n    ports:\n      - \"5432:5432\"\n  web:\n    image: x:1\n"

    def facts(self, image, ports, line=2):
        return {"deployment": {"compose": [
            {"name": "db", "image": image, "ports": ports, "file": "docker-compose.yml", "line": line}]}}

    def test_flags_a_published_datastore_port_at_the_mapping_line(self):
        found = run(S.detect_published_datastore_ports, {"docker-compose.yml": self.COMPOSE},
                    self.facts("postgres:16", ["5432:5432"]))
        self.assertEqual(found[0].locations, ("docker-compose.yml:5",))  # the port line, not the `db:` key

    def test_falls_back_to_the_service_line_when_the_mapping_is_not_found(self):
        found = run(S.detect_published_datastore_ports, {}, self.facts("postgres:16", ["5432:5432"]))
        self.assertEqual(found[0].locations, ("docker-compose.yml:2",))

    def test_a_port_in_the_next_service_is_not_picked_up(self):
        compose = "services:\n  db:\n    image: postgres:16\n  web:\n    ports:\n      - \"5432:5432\"\n"
        found = run(S.detect_published_datastore_ports, {"docker-compose.yml": compose},
                    self.facts("postgres:16", ["5432:5432"]))
        self.assertEqual(found[0].locations, ("docker-compose.yml:2",))

    def test_loopback_binding_and_container_only_ports_are_fine(self):
        loopback = self.facts("postgres:16", ["127.0.0.1:5432:5432"])
        self.assertEqual(run(S.detect_published_datastore_ports, {}, loopback), [])
        self.assertEqual(run(S.detect_published_datastore_ports, {}, self.facts("postgres:16", ["5432"])), [])

    def test_a_published_web_port_is_not_a_datastore(self):
        self.assertEqual(run(S.detect_published_datastore_ports, {}, self.facts("myorg/web:1", ["80:80"])), [])


class RootContainerTest(unittest.TestCase):
    def test_flags_a_dockerfile_with_no_user(self):
        found = run(S.detect_root_containers, {"Dockerfile": "FROM python:3.12\nCMD [\"x\"]\n"})
        self.assertEqual(found[0].locations, ("Dockerfile:1",))

    def test_a_non_root_user_clears_it_and_user_root_does_not(self):
        self.assertEqual(run(S.detect_root_containers, {"Dockerfile": "FROM python:3.12\nUSER app\n"}), [])
        self.assertEqual(len(run(S.detect_root_containers, {"Dockerfile": "FROM python:3.12\nUSER root\n"})), 1)

    def test_only_the_final_stage_counts(self):
        text = "FROM node:20 AS build\nUSER app\nFROM node:20\nCMD [\"x\"]\n"
        self.assertEqual(len(run(S.detect_root_containers, {"Dockerfile": text})), 1)

    def test_a_distroless_base_is_low_confidence(self):
        found = run(S.detect_root_containers, {"Dockerfile": "FROM gcr.io/distroless/static:nonroot\n"})
        self.assertEqual(found[0].confidence, "low")


class MigrationsTest(unittest.TestCase):
    MODEL = "from sqlalchemy import Column\n\nclass Item:\n    id = Column(1)\n"

    def test_flags_models_with_no_migrations(self):
        found = run(S.detect_models_without_migrations, {"api/models.py": self.MODEL})
        self.assertEqual(found[0].locations, ("api/models.py:4",))

    def test_a_migrations_folder_anywhere_clears_it(self):
        found = run(S.detect_models_without_migrations, {
            "api/models.py": self.MODEL, "api/app/migrations/0001.sql": "-- x\n"})
        self.assertEqual(found, [])

    def test_an_alembic_ini_clears_it(self):
        found = run(S.detect_models_without_migrations, {"api/models.py": self.MODEL, "alembic.ini": "[alembic]\n"})
        self.assertEqual(found, [])

    def test_a_repository_with_no_models_has_nothing_to_flag(self):
        self.assertEqual(run(S.detect_models_without_migrations, {"a.py": "x = 1\n"}), [])

    def test_other_orms_are_recognised(self):
        self.assertEqual(len(run(S.detect_models_without_migrations, {"A.java": "@Entity\nclass A {}\n"})), 1)
        self.assertEqual(len(run(S.detect_models_without_migrations, {"Db.cs": "class Db : DbContext {}\n"})), 1)


class SharedStoreTest(unittest.TestCase):
    def compose(self, a, b):
        return {"deployment": {"compose": [
            {"name": "api", "environment": {"DATABASE_URL": a}, "file": "c.yml", "line": 2},
            {"name": "worker", "environment": {"DATABASE_URL": b}, "file": "c.yml", "line": 6}]},
            "containers": [{"id": "svc-api", "compose_services": ["api"]},
                           {"id": "svc-worker", "compose_services": ["worker"]}]}

    def test_flags_a_connection_setting_shared_by_two_services(self):
        found = run(S.detect_shared_stores, {}, self.compose("postgres://db/x", "postgres://db/x"))
        self.assertEqual(found[0].containers, ("svc-api", "svc-worker"))
        self.assertEqual(found[0].locations, ("c.yml:2", "c.yml:6"))

    def test_different_values_are_not_shared(self):
        self.assertEqual(run(S.detect_shared_stores, {}, self.compose("postgres://db/a", "postgres://db/b")), [])

    def test_a_data_store_used_by_two_containers_is_flagged_once(self):
        facts = self.compose("postgres://db/x", "postgres://db/x")
        facts["data_stores"] = [{"id": "db", "name": "PostgreSQL", "used_by": ["svc-api", "svc-worker"],
                                 "evidence": ["c.yml:10"]}]
        found = run(S.detect_shared_stores, {}, facts)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].detail["store"], "db")


class CrossContainerImportTest(unittest.TestCase):
    FACTS = {"containers": [{"id": "api", "path": "api"}, {"id": "worker", "path": "worker"}]}

    def test_flags_a_python_import_of_another_containers_folder(self):
        found = run(S.detect_cross_container_imports, {
            "worker/t.py": "from api.app import app\nimport api.models\n", "api/app.py": "x = 1\n"}, self.FACTS)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].detail, {"from": "worker", "to": "api"})
        self.assertEqual(found[0].locations, ("worker/t.py:1", "worker/t.py:2"))

    def test_flags_a_relative_javascript_import(self):
        found = run(S.detect_cross_container_imports, {
            "worker/t.js": "import { x } from '../api/models';\n", "api/a.js": "x\n"}, self.FACTS)
        self.assertEqual(len(found), 1)

    def test_an_import_within_one_container_is_fine(self):
        found = run(S.detect_cross_container_imports, {
            "api/app.py": "from api.models import x\n", "worker/t.py": "x = 1\n"}, self.FACTS)
        self.assertEqual(found, [])

    def test_a_repository_with_one_root_container_has_no_cross_imports(self):
        facts = {"containers": [{"id": "app", "path": ""}]}
        self.assertEqual(run(S.detect_cross_container_imports, {"a.py": "from app import x\n"}, facts), [])


class HealthcheckTest(unittest.TestCase):
    def test_flags_a_dockerfile_with_no_healthcheck(self):
        found = run(S.detect_missing_healthchecks, {"Dockerfile": "FROM python:3.12\n"})
        self.assertEqual((found[0].confidence, found[0].detail["probe_defined_elsewhere"]), ("high", False))

    def test_a_healthcheck_clears_it_and_none_does_not(self):
        ok = {"Dockerfile": "FROM x:1\nHEALTHCHECK CMD curl -f /\n"}
        self.assertEqual(run(S.detect_missing_healthchecks, ok), [])
        self.assertEqual(len(run(S.detect_missing_healthchecks, {"Dockerfile": "FROM x:1\nHEALTHCHECK NONE\n"})), 1)

    def test_a_probe_elsewhere_lowers_confidence(self):
        found = run(S.detect_missing_healthchecks, {
            "Dockerfile": "FROM x:1\n", "docker-compose.yml": "services:\n  a:\n    healthcheck:\n      test: x\n"})
        self.assertEqual(found[0].confidence, "low")
        self.assertEqual(found[0].detail["probe_files"], ["docker-compose.yml"])

    def test_no_probe_anywhere_lists_no_files(self):
        found = run(S.detect_missing_healthchecks, {"Dockerfile": "FROM x:1\n"})
        self.assertEqual(found[0].detail["probe_files"], [])


class UnpinnedImageTest(unittest.TestCase):
    def test_flags_untagged_and_latest_images(self):
        found = run(S.detect_unpinned_images, {"Dockerfile": "FROM python\nFROM node:latest\nFROM python:3.12\n"},
                    {"deployment": {"compose": [{"name": "r", "image": "redis", "file": "c.yml", "line": 3}]}})
        self.assertEqual(found[0].locations, ("Dockerfile:1", "Dockerfile:2", "c.yml:3"))

    def test_pinned_digest_variable_and_scratch_are_fine(self):
        text = "FROM python:3.12\nFROM scratch\nFROM $BASE\nFROM x@sha256:abc\nFROM registry:5000/team/app:1.2\n"
        self.assertEqual(run(S.detect_unpinned_images, {"Dockerfile": text}), [])


class SignalSerialisationTest(unittest.TestCase):
    def test_locations_are_capped_and_the_total_is_kept(self):
        signal = S.Signal(lens="data", kind="k", summary="s", locations=tuple(f"f.py:{i}" for i in range(1, 13)))
        out = signal.to_dict("dat-01")
        self.assertEqual(len(out["locations"]), S.MAX_LOCATIONS)
        self.assertEqual(out["detail"]["locations_total"], 12)


if __name__ == "__main__":
    unittest.main()
