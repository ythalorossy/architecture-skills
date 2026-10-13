"""
Facts for the C4 diagrams: what a script can find without judgement.

- containers: things that run on their own (web API, web app, worker, CLI,
  function), found from project files and dependencies;
- data_stores: databases, caches, queues and vector stores the code connects to;
- external_systems: third-party APIs reached through an SDK or an HTTP client;
- components: per container, the projects/modules it is built from and the
  edges between them (the dependency graph, minus tests);
- code_components: per container, the packages/namespaces inside those modules
  and the imports between them (JVM, C#, Go);
- relationships: links between containers and stores found in compose
  depends_on and front-end dev-server proxies;
- endpoints, deployment, configuration and a per-container inventory
  (see code_facts.py).

Every item carries `evidence` (repo-relative file:line) so the C4 model the agent
writes on top of it can be checked. People and the purpose of each element
are left to that model.
"""
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from scripts.paths import GENERIC_URL_KEYS, REQUIREMENTS_FILE, in_test_dir, local_tag
    from scripts.projects import discover_all
    from scripts.python_projects import _distributions, normalize, _python_files
    from scripts.generate_docs import is_test_project
    from scripts import code_facts, code_types, go_projects
    from scripts.repo_index import RepoIndex, read_file_text, recording_skips
except ImportError:
    import code_facts, code_types, go_projects
    from paths import GENERIC_URL_KEYS, REQUIREMENTS_FILE, in_test_dir, local_tag
    from projects import discover_all
    from python_projects import _distributions, normalize, _python_files
    from generate_docs import is_test_project
    from repo_index import RepoIndex, read_file_text, recording_skips


SOURCE_EXTENSIONS = (".cs", ".fs", ".vb", ".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".vue", ".svelte",
                     ".java", ".kt", ".go")
MAX_EVIDENCE = 3


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "item"


# ---------- signals ----------

# (dependency or import name, kind, technology). First match wins per kind.
PYTHON_CONTAINER_SIGNALS = [
    ("fastapi", "web-api", "FastAPI"), ("flask", "web-api", "Flask"), ("django", "web-api", "Django"),
    ("starlette", "web-api", "Starlette"), ("aiohttp", "web-api", "aiohttp"), ("sanic", "web-api", "Sanic"),
    ("streamlit", "web-app", "Streamlit"), ("gradio", "web-app", "Gradio"), ("dash", "web-app", "Dash"),
    ("mcp", "mcp-server", "MCP SDK"), ("fastmcp", "mcp-server", "FastMCP"),
    ("celery", "worker", "Celery"), ("rq", "worker", "RQ"), ("dramatiq", "worker", "Dramatiq"),
    ("typer", "cli", "Typer"), ("click", "cli", "Click"),
]

NODE_CONTAINER_SIGNALS = [
    ("next", "web-app", "Next.js"), ("nuxt", "web-app", "Nuxt"), ("@angular/core", "web-app", "Angular"),
    ("react", "web-app", "React"), ("vue", "web-app", "Vue"), ("svelte", "web-app", "Svelte"),
    ("@nestjs/core", "web-api", "NestJS"), ("express", "web-api", "Express"), ("fastify", "web-api", "Fastify"),
    ("koa", "web-api", "Koa"), ("hono", "web-api", "Hono"),
    ("@modelcontextprotocol/sdk", "mcp-server", "MCP SDK"),
    ("electron", "desktop-app", "Electron"),
]

JAVA_CONTAINER_SIGNALS = [
    ("spring-boot-starter-web", "web-api", "Spring Boot"), ("spring-boot-starter-webflux", "web-api", "Spring WebFlux"),
    ("quarkus", "web-api", "Quarkus"), ("micronaut", "web-api", "Micronaut"),
    ("spring-boot", "app", "Spring Boot"),
]

# Code patterns (regex over source text) -> (kind, technology). kind is "store" or "external".
CODE_SIGNALS = [
    # .NET
    (r"\bUseSqlServer\s*\(|\bnew\s+SqlConnection\s*\(", "store", "SQL Server"),
    (r"\bUseNpgsql\s*\(|\bnew\s+NpgsqlConnection\s*\(", "store", "PostgreSQL"),
    (r"\bUseMySql\s*\(|\bUseMySQL\s*\(", "store", "MySQL"),
    (r"\bUseSqlite\s*\(", "store", "SQLite"),
    (r"\bUseCosmos\s*\(|\bnew\s+CosmosClient\s*\(", "store", "Azure Cosmos DB"),
    (r"\bnew\s+MongoClient\s*\(", "store", "MongoDB"),
    (r"\bConnectionMultiplexer\.Connect|\bAddStackExchangeRedisCache\s*\(", "store", "Redis"),
    (r"\bnew\s+Elastic(search)?Client\s*\(", "store", "Elasticsearch"),
    (r"\bnew\s+BlobServiceClient\s*\(", "store", "Azure Blob Storage"),
    (r"\bnew\s+ServiceBusClient\s*\(", "store", "Azure Service Bus"),
    (r"\bnew\s+AmazonS3Client\s*\(", "store", "Amazon S3"),
    (r"\bnew\s+GraphServiceClient\s*\(|\bGraphServiceClient\.builder\(", "external", "Microsoft Graph"),
    # JVM (Spring Data and common clients)
    (r"\b(?:StringRedisTemplate|RedisTemplate|ReactiveRedisTemplate|RedisConnectionFactory|LettuceConnectionFactory|JedisPool|RedissonClient)\b", "store", "Redis"),
    (r"\b(?:MongoTemplate|MongoRepository|ReactiveMongoTemplate)\b", "store", "MongoDB"),
    (r"\bKafkaTemplate\b|@KafkaListener\b", "store", "Kafka"),
    (r"\bRabbitTemplate\b|@RabbitListener\b", "store", "RabbitMQ"),
    (r"\bElasticsearchOperations\b|\bElasticsearchClient\b", "store", "Elasticsearch"),
    (r"\bS3Client\.builder\(|\bAmazonS3ClientBuilder\b", "store", "Amazon S3"),
    (r"\bSqsClient\b|@SqsListener\b", "store", "Amazon SQS"),
]

# Imported module / package name -> (kind, technology) for Python and Node.js.
IMPORT_SIGNALS = {
    # Python
    "psycopg": ("store", "PostgreSQL"), "psycopg2": ("store", "PostgreSQL"), "asyncpg": ("store", "PostgreSQL"),
    "pymysql": ("store", "MySQL"), "MySQLdb": ("store", "MySQL"), "pyodbc": ("store", "SQL Server"), "pymssql": ("store", "SQL Server"),
    "sqlite3": ("store", "SQLite"), "pymongo": ("store", "MongoDB"), "motor": ("store", "MongoDB"),
    "redis": ("store", "Redis"), "elasticsearch": ("store", "Elasticsearch"),
    "lancedb": ("store", "LanceDB"), "chromadb": ("store", "Chroma"), "qdrant_client": ("store", "Qdrant"),
    "pinecone": ("store", "Pinecone"), "pika": ("store", "RabbitMQ"), "kafka": ("store", "Kafka"),
    "anthropic": ("external", "Anthropic API"), "openai": ("external", "OpenAI API"),
    "google.generativeai": ("external", "Google Gemini API"), "google.genai": ("external", "Google Gemini API"),
    "boto3": ("external", "AWS"), "stripe": ("external", "Stripe"), "twilio": ("external", "Twilio"),
    "sendgrid": ("external", "SendGrid"), "slack_sdk": ("external", "Slack API"),
    "msgraph": ("external", "Microsoft Graph"),
    # Node.js
    "pg": ("store", "PostgreSQL"), "postgres": ("store", "PostgreSQL"), "mysql": ("store", "MySQL"),
    "mysql2": ("store", "MySQL"), "mssql": ("store", "SQL Server"), "tedious": ("store", "SQL Server"),
    "mongodb": ("store", "MongoDB"), "mongoose": ("store", "MongoDB"), "ioredis": ("store", "Redis"),
    "better-sqlite3": ("store", "SQLite"),  # "sqlite3" is listed with Python above
    "@elastic/elasticsearch": ("store", "Elasticsearch"), "kafkajs": ("store", "Kafka"), "amqplib": ("store", "RabbitMQ"),
    "@anthropic-ai/sdk": ("external", "Anthropic API"), "@google/generative-ai": ("external", "Google Gemini API"),
    "@aws-sdk": ("external", "AWS"), "aws-sdk": ("external", "AWS"), "@sendgrid/mail": ("external", "SendGrid"),
    "@slack/web-api": ("external", "Slack API"), "@microsoft/microsoft-graph-client": ("external", "Microsoft Graph"),
    "@sentry/node": ("external", "Sentry"), "@sentry/react": ("external", "Sentry"), "sentry_sdk": ("external", "Sentry"),
    "applicationinsights": ("external", "Azure Application Insights"), "dd-trace": ("external", "Datadog"),
    "ddtrace": ("external", "Datadog"), "newrelic": ("external", "New Relic"),
    # Go (matched as an import-path prefix)
    "github.com/lib/pq": ("store", "PostgreSQL"), "github.com/jackc/pgx": ("store", "PostgreSQL"),
    "github.com/go-sql-driver/mysql": ("store", "MySQL"), "github.com/mattn/go-sqlite3": ("store", "SQLite"),
    "modernc.org/sqlite": ("store", "SQLite"), "github.com/microsoft/go-mssqldb": ("store", "SQL Server"),
    "github.com/redis/go-redis": ("store", "Redis"), "github.com/go-redis/redis": ("store", "Redis"),
    "go.mongodb.org/mongo-driver": ("store", "MongoDB"), "github.com/segmentio/kafka-go": ("store", "Kafka"),
    "github.com/IBM/sarama": ("store", "Kafka"), "github.com/rabbitmq/amqp091-go": ("store", "RabbitMQ"),
    "github.com/nats-io/nats.go": ("store", "NATS"), "github.com/elastic/go-elasticsearch": ("store", "Elasticsearch"),
    "github.com/aws/aws-sdk-go": ("external", "AWS"), "github.com/aws/aws-sdk-go-v2": ("external", "AWS"),
    "github.com/stripe/stripe-go": ("external", "Stripe"), "github.com/getsentry/sentry-go": ("external", "Sentry"),
    "github.com/microsoftgraph/msgraph-sdk-go": ("external", "Microsoft Graph"),
}

# NuGet / Maven package prefixes -> (kind, technology).
PACKAGE_SIGNALS = [
    ("AWSSDK.", "external", "AWS"), ("Stripe.net", "external", "Stripe"), ("SendGrid", "external", "SendGrid"),
    ("Twilio", "external", "Twilio"), ("Anthropic", "external", "Anthropic API"), ("OpenAI", "external", "OpenAI API"),
    ("Azure.AI.OpenAI", "external", "Azure OpenAI"),
    ("Microsoft.Graph", "external", "Microsoft Graph"), ("microsoft-graph", "external", "Microsoft Graph"),
    ("Microsoft.ApplicationInsights", "external", "Azure Application Insights"),
    ("Sentry", "external", "Sentry"), ("Datadog.Trace", "external", "Datadog"),
    ("NewRelic.Agent", "external", "New Relic"), ("OpenTelemetry.Exporter", "external", "OpenTelemetry collector"),
    ("postgresql", "store", "PostgreSQL"), ("mysql-connector", "store", "MySQL"), ("mssql-jdbc", "store", "SQL Server"),
    ("spring-boot-starter-data-mongodb", "store", "MongoDB"), ("spring-boot-starter-data-redis", "store", "Redis"),
    ("spring-kafka", "store", "Kafka"), ("spring-boot-starter-amqp", "store", "RabbitMQ"),
]

# docker-compose images -> technology of a data store.
COMPOSE_STORES = [
    ("postgres", "PostgreSQL"), ("mysql", "MySQL"), ("mariadb", "MariaDB"), ("mongo", "MongoDB"),
    ("redis", "Redis"), ("elasticsearch", "Elasticsearch"), ("opensearch", "OpenSearch"),
    ("rabbitmq", "RabbitMQ"), ("kafka", "Kafka"), ("mssql", "SQL Server"), ("azure-sql-edge", "SQL Server"),
    ("minio", "MinIO"), ("memcached", "Memcached"), ("qdrant", "Qdrant"), ("chroma", "Chroma"),
]

HTTP_CLIENT = re.compile(
    r"\bHttpClient\b|\bRestClient\b|\bFeignClient\b|\bHttpURLConnection\b|\brequests\.|\bhttpx\b|\baiohttp\b|\burllib\b|"
    r"\baxios\b|\bfetch\(|\bky\b|\bgot\(|\bRestTemplate\b|\bWebClient\b|\bOkHttp|\bhttp\.(?:Get|Post|NewRequest)|\bresty\b"
)
# SOAP clients (WCF, JAX-WS, zeep, node-soap) call their endpoint without an HTTP client.
SOAP_CLIENT = re.compile(r"\bEndpointAddress\b|\bClientBase<|@WebServiceClient\b|\bzeep\.|\bsoap\.createClient")
URL = re.compile(r"""https?://([A-Za-z0-9.-]+\.[A-Za-z]{2,})""")
IGNORED_HOSTS = re.compile(
    r"(^|\.)(localhost|example\.(com|org)|w3\.org|json-schema\.org|schemas\.[a-z.]+|xmlsoap\.org|"
    r"microsoft\.com|aka\.ms|github\.com|githubusercontent\.com|npmjs\.(com|org)|pypi\.org|"
    r"python\.org|mozilla\.org|swagger\.io|openapis\.org|apache\.org|nuget\.org|"
    r"database\.windows\.net|readthedocs\.io|tempuri\.org)$"
)
# Hosts of well-known APIs -> technology, so a raw URL lands on the same box as
# the SDK. Checked before IGNORED_HOSTS (graph.microsoft.com is a microsoft.com host).
KNOWN_HOSTS = {"graph.microsoft.com": "Microsoft Graph"}
PY_IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.MULTILINE)
JS_IMPORT = re.compile(r"""(?:from\s+|require\(\s*|import\s*\(\s*|import\s+)['"]([^'"]+)['"]""")


# ---------- helpers ----------

def _wanted_host(host):
    """A host worth reporting as an external system: a known API, or not on the ignore list."""
    return host in KNOWN_HOSTS or not IGNORED_HOSTS.search(host)


def _rel(repo, path):
    return Path(path).resolve().relative_to(repo).as_posix()


def _line_of(text, index):
    return text.count("\n", 0, index) + 1


def _file_text(path):
    """File text, or "" when unreadable or larger than MAX_TEXT_BYTES (generated bundles, data dumps)."""
    return read_file_text(path, "c4_facts")


def _is_vendored(rel_parts):
    """Third-party code checked into the repo: vendor/ folders, ASP.NET wwwroot/lib (libman), minified bundles."""
    folders = [part.lower() for part in rel_parts[:-1]]
    return (
        any(part in ("vendor", "vendors") for part in folders)
        or any(a == "wwwroot" and b == "lib" for a, b in zip(folders, folders[1:]))
        or re.search(r"\.min\.m?js$", rel_parts[-1].lower()) is not None
    )


def _source_files(repo, test_dirs, index=None):
    files = []
    candidates = RepoIndex.ensure(index, repo).walk(lambda name: name.endswith(SOURCE_EXTENSIONS))
    for file in candidates:
        rel_parts = file.resolve().relative_to(repo).parts
        if in_test_dir(rel_parts[:-1]):
            continue
        if _is_vendored(rel_parts):
            continue
        if any(file.resolve().is_relative_to(d) for d in test_dirs):
            continue
        files.append(file.resolve())
    return files


def _masked(text, suffix, strings):
    """``text`` with its comments blanked, and its string contents too when asked.

    One pass per file over the same masker the Level 4 parsers use, instead of
    re-reading the line in front of every match: a quote or a ``#`` inside a
    literal is no longer mistaken for the thing it looks like.
    """
    language = code_types.MASK_LANGUAGES.get(suffix.lower())
    if language is None:
        return text
    return code_types.mask(text, language, strings=strings, comments=True)


def _strip_json_comments(text):
    return re.sub(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/', lambda m: m.group(1) or "", text, flags=re.DOTALL)


def _config_urls(text):
    """(setting name, host) for every URL value in a JSON config, e.g. ("PaymentsUrl", "payments.example")."""
    try:
        data = json.loads(_strip_json_comments(text))
    except ValueError:
        return []

    found = []

    def visit(value, keys):
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, keys + [key])
        elif isinstance(value, list):
            for child in value:
                visit(child, keys)
        elif isinstance(value, str):
            match = URL.match(value.strip())
            if match and _wanted_host(match.group(1).lower()):
                # Drop year/number keys and generic leaf names: the setting is what's left.
                named = [k for k in keys if not k.isdigit()]
                while len(named) > 1 and named[-1].lower() in GENERIC_URL_KEYS:
                    named.pop()
                found.append((":".join(named[-1:]) or "config", match.group(1).lower()))

    visit(data, [])
    return found


# ---------- containers ----------

def _dotnet_containers(repo, projects):
    containers = []
    for project in projects:
        if project["ecosystem"] != ".NET" or project["in_solution"] is False or is_test_project(project["id"]):
            continue
        text = _file_text(project["path"])
        try:
            root = ET.fromstring(text.encode("utf-8"))
        except ET.ParseError:
            continue
        sdk = root.attrib.get("Sdk", "")
        props = {local_tag(e): (e.text or "").strip() for e in root.iter()}
        packages = [e.attrib.get("Include", "") for e in root.iter() if local_tag(e) == "PackageReference"]
        if "Microsoft.NET.Test.Sdk" in packages:
            continue

        framework = props.get("TargetFramework") or props.get("TargetFrameworks", "").split(";")[0]
        if "AzureFunctionsVersion" in props:
            kind, technology = "function", "Azure Functions"
        elif sdk.endswith(".Web"):
            kind, technology = "web-api", "ASP.NET Core"
        elif sdk.endswith(".BlazorWebAssembly"):
            kind, technology = "web-app", "Blazor WebAssembly"
        elif sdk.endswith(".Worker"):
            kind, technology = "worker", ".NET Worker Service"
        elif props.get("OutputType", "").lower() in ("exe", "winexe"):
            kind, technology = "app", ".NET console app"
        else:
            continue

        containers.append({
            "name": project["id"],
            "kind": kind,
            "technology": f"{technology}, {framework}" if framework else technology,
            "path": _rel(repo, project["path"].parent),
            "root": project["path"],
            "evidence": [f"{project['relative_path']}: Sdk=\"{sdk}\"" if sdk else project["relative_path"]],
        })
    return containers


def _signal_match(names, signals):
    kinds = {}
    for name, kind, technology in signals:
        if name in names and kind not in kinds:
            kinds[kind] = technology
    return kinds


def _python_imports(files):
    names = set()
    for file in files:
        for match in PY_IMPORT.finditer(_file_text(file)):
            module = match.group(1) or match.group(2)
            parts = module.split(".")
            names.add(parts[0])
            if len(parts) > 1:
                names.add(".".join(parts[:2]))
    return names


def _requirements_services(repo, index, packaged):
    """
    Folders with their own requirements*.txt and no pyproject.toml/setup.py:
    small services often have only that. One candidate each; folders inside
    a packaged distribution, tests and docs are skipped.
    """
    def wanted(name):
        return REQUIREMENTS_FILE.match(name)

    files = RepoIndex.ensure(index, repo).walk(wanted)
    folders = set()
    for file in files:
        folder = file.parent.resolve()
        parts = [p.lower() for p in folder.relative_to(repo).parts]
        if in_test_dir(parts) or any(p in ("docs", "doc") for p in parts):
            continue
        if any(folder == d or folder.is_relative_to(d) for d in packaged):
            continue
        folders.add(folder)
    return [
        {"name": folder.name if folder != repo else repo.name, "directory": folder, "file": None, "requirements": []}
        for folder in sorted(folders)
    ]


def _python_containers(repo, index):
    repo = Path(repo).resolve()
    distributions = _distributions(repo, index)
    distributions += _requirements_services(repo, index, [d["directory"] for d in distributions])

    containers = []
    for dist in distributions:
        directory = dist["directory"]
        # A service inside this folder scans its own code, not this one's.
        nested = [d["directory"] for d in distributions if d["directory"] != directory and d["directory"].is_relative_to(directory)]
        requirements = set(dist["requirements"])
        for req_file in directory.glob("requirements*.txt"):
            for line in _file_text(req_file).splitlines():
                match = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)", line)
                if match:
                    requirements.add(normalize(match.group(1)))

        code = [
            f for f in _python_files(directory, index)
            if not in_test_dir(f.relative_to(directory).parts[:-1])
            and not any(f.is_relative_to(n) for n in nested)
        ]
        imports = _python_imports(code)
        names = {normalize(n) for n in requirements} | {normalize(n) for n in imports}
        kinds = _signal_match(names, [(normalize(n), k, t) for n, k, t in PYTHON_CONTAINER_SIGNALS])

        manifest = dist["file"]
        if manifest is not None and manifest.name == "pyproject.toml" and "[project.scripts]" in _file_text(manifest):
            kinds.setdefault("cli", "CLI")
        if not kinds:
            continue

        evidence = [f"{_rel(repo, manifest) if manifest else _rel(repo, directory)}: {', '.join(kinds.values())}"]
        containers.append({
            "name": dist["name"],
            "kind": " + ".join(kinds),
            "technology": "Python, " + ", ".join(kinds.values()),
            "path": _rel(repo, directory) if directory != repo else ".",
            "root": manifest.resolve() if manifest else None,
            "evidence": evidence,
        })
    return containers


def _node_containers(repo, index):
    containers = []
    index = RepoIndex.ensure(index, repo)
    for file in index.walk(lambda name: name == "package.json"):
        data = index.read_json(file)
        if data is None:
            continue
        if data.get("workspaces"):
            continue
        dependencies = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
        runtime = set(data.get("dependencies") or {})
        kinds = _signal_match(set(dependencies), NODE_CONTAINER_SIGNALS)
        # A server framework only in devDependencies is usually a dev server, not the app.
        kinds = {k: t for k, t in kinds.items() if k == "web-app" or any(n in runtime for n, kk, _ in NODE_CONTAINER_SIGNALS if kk == k)}
        if data.get("bin"):
            kinds.setdefault("cli", "CLI")
        if not kinds and (data.get("scripts") or {}).get("start"):
            kinds["app"] = "Node.js"
        if not kinds:
            continue
        containers.append({
            "name": data.get("name") or file.parent.name,
            "kind": " + ".join(kinds),
            "technology": ", ".join((["Node.js"] if "web-app" not in kinds else []) + [t for t in kinds.values() if t != "Node.js"]),
            "path": _rel(repo, file.parent) if file.parent.resolve() != repo else ".",
            "root": file.resolve(),
            "evidence": [f"{_rel(repo, file)}: {', '.join(kinds.values())}"],
        })
    return containers


def _java_containers(repo, projects, index):
    containers = []
    for project in projects:
        if not project["ecosystem"].startswith("Java") or is_test_project(project["id"]):
            continue
        path = project["path"]
        text = _file_text(path) if path.is_file() else ""
        kinds = _signal_match({s for s, _, _ in JAVA_CONTAINER_SIGNALS if s in text}, JAVA_CONTAINER_SIGNALS)
        if "web-api" in kinds:
            kinds.pop("app", None)
        if re.search(r"<packaging>\s*war\s*</packaging>", text):
            kinds.setdefault("web-app", "Java web app (WAR)")
        if re.search(r"\bid\s*\(?\s*['\"]application['\"]|^\s*application\s*$", text, re.MULTILINE):
            kinds.setdefault("app", "Java application")
        if not kinds:
            continue
        # A module that only depends on Spring (a library) is not a container:
        # it needs a main class or a packaging plugin.
        module_dir = path.parent if path.is_file() else path
        if not (
            re.search(r"spring-boot-maven-plugin|quarkus-maven-plugin|micronaut-maven-plugin|<packaging>\s*war|org\.springframework\.boot['\"]?\)?\s*version|id\s*\(?\s*['\"]application", text)
            or _has_jvm_main(module_dir, index)
        ):
            continue
        containers.append({
            "name": project["id"],
            "kind": " + ".join(kinds),
            "technology": ", ".join(kinds.values()),
            "path": _rel(repo, path.parent if path.is_file() else path),
            "root": path,
            "evidence": [f"{project['relative_path']}: {', '.join(kinds.values())}"],
        })
    return containers


def _has_jvm_main(module_dir, index):
    base = Path(module_dir).resolve()
    candidates = RepoIndex.ensure(index, base).walk(lambda n: n.endswith((".java", ".kt")), under=base)
    for file in candidates:
        if in_test_dir(file.resolve().relative_to(base).parts[:-1]):
            continue
        text = _file_text(file)
        if "@SpringBootApplication" in text or "@QuarkusMain" in text or re.search(r"\bstatic\s+void\s+main\s*\(|^fun\s+main\s*\(", text, re.MULTILINE):
            return True
    return False


def _go_containers(repo, index):
    containers = []
    for directory, module, kind, technology in go_projects.main_packages(repo, index):
        relative = _rel(repo, directory)
        name = directory.name if directory != module["dir"] else module["path"].rsplit("/", 1)[-1]
        containers.append({
            "name": name, "kind": kind, "technology": technology,
            "path": relative, "root": directory,
            "evidence": [f"{relative}: package main ({technology})"],
        })
    return containers


def _yaml_urls(text):
    """(setting path, host, line) for URL values in YAML or .properties text, tracking the key path by indentation."""
    found, stack = [], []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "!")):
            continue
        prop = re.match(r"^([\w.\-\[\]]+)\s*[=:]\s*(\S.*)$", stripped) if "=" in stripped and ":" not in stripped.split("=")[0] else None
        if prop:
            keys, value = prop.group(1).split("."), prop.group(2)
        else:
            m = re.match(r"^(-\s*)?([\w.\-\"']+)\s*:\s*(.*)$", stripped)
            if not m:
                continue
            indent = len(line) - len(line.lstrip())
            while stack and stack[-1][0] >= indent:
                stack.pop()
            key = m.group(2).strip("\"'")
            if not m.group(3) or m.group(3).startswith(("|", ">")):
                stack.append((indent, key))
                continue
            keys, value = [k for _, k in stack] + [key], m.group(3)
        url = URL.match(value.strip().strip("\"'").split("${")[-1].split(":", 1)[-1] if value.strip().startswith("${") else value.strip().strip("\"'"))
        if url and _wanted_host(url.group(1).lower()):
            found.append((".".join(keys), url.group(1).lower(), number))
    return found


def _compose_services(repo, index=None):
    """(service, image, build context, file, line) from docker-compose files.

    Reads them with code_facts.compose_services, the one compose parser, so
    service names match the relationships and the deployment section.
    """
    index = RepoIndex.ensure(index, repo)
    return [
        {"name": s["name"], "image": s["image"], "build": s["build"],
         "file": Path(repo) / s["file"], "line": s["line"]}
        for s in code_facts.compose_services(index)
    ]


# ---------- main ----------

def _container_scopes(repo, containers, projects, graph):
    """Directories whose files belong to each container: its own folder plus every project it references."""
    path_to_id = {p["path"]: p["id"] for p in projects}
    id_to_dir = {p["id"]: (p["path"].parent if p["path"].is_file() else p["path"]) for p in projects}

    for container in containers:
        scope = {(repo / container["path"]).resolve()}
        root_id = path_to_id.get(container["root"]) if container.get("root") else None
        if root_id in graph:
            seen, stack = set(), [root_id]
            while stack:
                node = stack.pop()
                if node in seen or node not in graph:
                    continue
                seen.add(node)
                stack += graph[node]
            scope |= {id_to_dir[n] for n in seen if n in id_to_dir}
            container["root_component"] = root_id
        container["scope"] = scope


def _components(repo, container, projects, graph, all_containers):
    """Component graph of one container: reachable projects, or the module nodes inside its folder."""
    by_id = {p["id"]: p for p in projects}
    root = container.get("root_component")

    if root:
        nodes, stack = [], [root]
        while stack:
            node = stack.pop()
            if node in nodes or node not in graph:
                continue
            nodes.append(node)
            stack += graph[node]
    else:
        directory = (repo / container["path"]).resolve()
        # Nested containers (a package inside this one's folder) own their own nodes.
        others = [(repo / c["path"]).resolve() for c in all_containers if c is not container]
        nodes = []
        for node, project in by_id.items():
            if node not in graph:
                continue
            path = project["path"]
            if not path.resolve().is_relative_to(directory):
                continue
            if any(o != directory and o.is_relative_to(directory) and path.resolve().is_relative_to(o) for o in others):
                continue
            nodes.append(node)

    nodes = [
        n for n in nodes
        if not is_test_project(n)
        and not in_test_dir(Path(by_id[n]["relative_path"]).parts)
    ]
    node_set = set(nodes)
    return {
        "nodes": {
            n: {"path": by_id[n]["relative_path"], "group": by_id[n]["group"]}
            for n in sorted(nodes)
        },
        "edges": {n: [t for t in graph[n] if t in node_set] for n in sorted(nodes)},
    }


def _inside(path, folder):
    """True when the path string is the folder or lies below it."""
    return path == folder or path.startswith(folder if folder.endswith(os.sep) else folder + os.sep)


class _Ownership:
    """
    Which containers, and which component in each, own a file.

    Every evidence line asks this, so it is computed once per file: each
    component base is resolved once, and paths are compared as strings.
    (Path.resolve and Path.is_relative_to per container, component and line
    took 95% of the run on a 20-package monorepo.)

    A file belongs to every container whose scope holds it; within a
    container, the component with the deepest base wins (the first one on a
    tie), and a "(files)" component only owns files directly in its folder.
    """

    def __init__(self, runnable, by_id):
        self._containers = []
        for container in runnable:
            bases = []
            for node in container["components"]["nodes"]:
                path = by_id[node]["path"].resolve()
                base = path.parent if path.is_file() and path.suffix not in (".py",) else path
                bases.append((node, str(base), len(base.parts), node.endswith(" (files)")))
            self._containers.append((container["id"], [str(d) for d in container["scope"]], bases))
        self._cache = {}

    def __call__(self, file):
        key = str(file)
        if key not in self._cache:
            parent = os.path.dirname(key)
            result = []
            for container_id, scope, bases in self._containers:
                if not any(_inside(key, folder) for folder in scope):
                    continue
                best, best_len = None, -1
                for node, base, length, files_only in bases:
                    matches = parent == base if files_only else _inside(key, base)
                    if matches and length > best_len:
                        best, best_len = node, length
                result.append((container_id, best))
            self._cache[key] = result
        return self._cache[key]


def collect_facts(repo_path, graph, index=None, discovery=None):
    """Collect the facts, recording every file dropped for its size.

    The scanners below read through module-level helpers with no collector
    of their own, so the run's collector is installed for the call.
    """
    index = RepoIndex.ensure(index, Path(repo_path).resolve())
    with recording_skips(index.collector):
        return _collect_facts(repo_path, graph, index=index, discovery=discovery)


def _collect_facts(repo_path, graph, index=None, discovery=None):
    repo = Path(repo_path).resolve()
    index = RepoIndex.ensure(index, repo)
    if discovery is None:
        discovery = discover_all(repo, index)
    projects = [p for p in discovery["projects"] if p["in_solution"] is not False]

    containers = (
        _dotnet_containers(repo, projects)
        + _python_containers(repo, index)
        + _node_containers(repo, index)
        + _java_containers(repo, projects, index)
        + _go_containers(repo, index)
    )

    stores, externals = {}, {}
    compose_stores, compose_map = [], {}

    # docker-compose: build services are (or confirm) containers; known images are data stores.
    for service in _compose_services(repo, index):
        evidence = f"{_rel(repo, service['file'])}:{service['line']}"
        image = (service["image"] or "").lower()
        store = next((tech for key, tech in COMPOSE_STORES if key in image.split(":")[0]), None)
        if store:
            compose_stores.append((store, service))
            compose_map[service["name"]] = ("store", store)
        elif service["build"]:
            context = (service["file"].parent / service["build"]).resolve()
            match = next((c for c in containers if c["path"] and (repo / c["path"]).resolve() == context), None)
            if match is None:
                # Build context is a parent folder (a Maven/Gradle/.NET multi-module root):
                # pick the runnable container below it, preferring a web API.
                inside = [c for c in containers if c["path"] and (repo / c["path"]).resolve().is_relative_to(context)]
                dockerfile = _file_text(context / "Dockerfile")
                mentioned = [c for c in inside if Path(c["path"]).name in dockerfile] or inside
                web = [c for c in mentioned if "web-api" in c["kind"]]
                match = (web or mentioned or [None])[0]
            if match is None and context.is_relative_to(repo):
                match = {
                    "name": service["name"], "kind": "service", "technology": "Docker",
                    "path": _rel(repo, context) if context != repo else ".", "root": None, "evidence": [],
                }
                containers.append(match)
            if match is not None:
                match["evidence"].append(f"{evidence} (compose service {service['name']})")
                match.setdefault("compose_services", []).append(service["name"])
                compose_map[service["name"]] = ("container", match)
        elif image:
            match = {
                "name": service["name"], "kind": "service", "technology": image,
                "path": None, "root": None, "evidence": [evidence], "compose_services": [service["name"]],
            }
            containers.append(match)
            compose_map[service["name"]] = ("container", match)

    # Nothing runnable found: treat the whole repository as one container, so
    # the component level still has a home.
    if not containers and graph:
        containers.append({
            "name": repo.name, "kind": "unknown", "technology": "", "path": ".", "root": None,
            "evidence": ["no entry point detected; whole repository"],
        })

    used_ids = set()
    for container in containers:
        # "Submission.API (articles/src/...)" -> submission-api, then -2, -3 on collision.
        base = slug(re.sub(r"\s*\(.*\)$", "", container["name"]))
        candidate, number = base, 2
        while candidate in used_ids:
            candidate, number = f"{base}-{number}", number + 1
        container["id"] = candidate
        used_ids.add(candidate)

    runnable = [c for c in containers if c["path"] is not None]
    _container_scopes(repo, runnable, projects, graph)
    for container in runnable:
        container["components"] = _components(repo, container, projects, graph, runnable)

    test_dirs = [
        (p["path"].parent if p["path"].is_file() else p["path"]).resolve()
        for p in projects if is_test_project(p["id"])
    ]
    by_id = {p["id"]: p for p in projects}

    owners = _Ownership(runnable, by_id)

    def owner_container(file):
        found = owners(Path(file).resolve())
        # Most specific container: the one whose own folder holds the file.
        found.sort(key=lambda o: -len((repo / next(c for c in runnable if c["id"] == o[0])["path"]).resolve().parts))
        return found[0][0] if found else None

    def record(registry, key, entry, file, line):
        found = owners(file)
        item = registry.setdefault(key, entry)
        item.setdefault("files", set()).add(Path(file).resolve())
        evidence = f"{_rel(repo, file)}:{line}"
        # One line per file is enough evidence.
        if not any(e.split(":")[0] == evidence.split(":")[0] for e in item["evidence"]):
            # Evidence from code a container owns comes first.
            owned = item.setdefault("owned", [])
            if found:
                item["evidence"].insert(len([e for e in item["evidence"] if e in owned]), evidence)
                owned.append(evidence)
            else:
                item["evidence"].append(evidence)
            del item["evidence"][MAX_EVIDENCE:]
        for container_id, component in found:
            item["used_by"].add(container_id)
            if component:
                item["used_by_components"].setdefault(container_id, set()).add(component)

    def new_entry(technology):
        return {"technology": technology, "evidence": [], "used_by": set(), "used_by_components": {}}

    for technology, service in compose_stores:
        record(stores, technology, new_entry(technology), service["file"].resolve(), service["line"])

    source_files = _source_files(repo, test_dirs, index)
    for file in source_files:
        text = _file_text(file)
        # Code only: a name listed in a pattern table or recalled in a comment
        # is not a dependency. URLs keep their literals, which is where they live.
        code = _masked(text, file.suffix, strings=True)
        prose_free = _masked(text, file.suffix, strings=False)

        for pattern, kind, technology in CODE_SIGNALS:
            match = re.search(pattern, code)
            if match:
                record(stores if kind == "store" else externals, technology, new_entry(technology), file, _line_of(text, match.start()))

        if file.suffix == ".py":
            imports = [(m.group(1) or m.group(2), m.start()) for m in PY_IMPORT.finditer(text)]
        elif file.suffix in (".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"):
            imports = [(m.group(1), m.start()) for m in JS_IMPORT.finditer(text)]
        elif file.suffix == ".go":
            imports = [(name, max(text.find(f'"{name}"'), 0)) for name in code_facts.go_imports(text)]
        else:
            imports = []
        for module, _match_pos in imports:
            if file.suffix == ".go":
                hit = next((v for k, v in IMPORT_SIGNALS.items() if "/" in k and "." in k.split("/")[0] and (module == k or module.startswith(k + "/"))), None)
            else:
                parts = module.split("/") if "/" in module else module.split(".")
                candidates = [module, parts[0], "/".join(parts[:2]) if module.startswith("@") else ".".join(parts[:2])]
                hit = next((IMPORT_SIGNALS[c] for c in candidates if c in IMPORT_SIGNALS), None)
            if hit:
                kind, technology = hit
                record(stores if kind == "store" else externals, technology, new_entry(technology), file, _line_of(text, _match_pos))

        soap = SOAP_CLIENT.search(code)
        if soap or HTTP_CLIENT.search(code):
            for match in URL.finditer(prose_free):
                host = match.group(1).lower()
                key = KNOWN_HOSTS.get(host) or (None if IGNORED_HOSTS.search(host) else host)
                if key:
                    record(externals, key, new_entry("SOAP" if soap and key == host else key), file, _line_of(text, match.start()))

    # Package references (NuGet, Maven) that imply a store or a third-party API.
    for project in projects:
        if is_test_project(project["id"]) or not project["path"].is_file():
            continue
        # None when the manifest is unreadable or past the size cap.
        text = index.read_text(project["path"]) or ""
        for prefix, kind, technology in PACKAGE_SIGNALS:
            match = re.search(r"""(Include="|<artifactId>|['":])""" + re.escape(prefix), text)
            if match:
                record(stores if kind == "store" else externals, technology, new_entry(technology), project["path"], _line_of(text, match.start()))

    # URLs in config files. A setting that holds one host becomes that host; a
    # setting that maps to several hosts (per state, per year) stays one box
    # named after the setting.
    config_urls = {}
    appsettings = index.walk(lambda name: re.match(r"appsettings.*\.json$", name))
    for file in appsettings:
        text = _file_text(file)
        for setting, host in _config_urls(text):
            if host in KNOWN_HOSTS:
                record(externals, KNOWN_HOSTS[host], new_entry(KNOWN_HOSTS[host]), file.resolve(), _line_of(text, max(text.find(host), 0)))
                continue
            config_urls.setdefault(setting, []).append((host, file, _line_of(text, max(text.find(host), 0))))
    config_ymls = index.walk(lambda name: re.match(r"(application|bootstrap)[\w-]*\.(ya?ml|properties)$|^config\.ya?ml$|^settings\.ya?ml$", name))
    for file in config_ymls:
        if in_test_dir(file.relative_to(repo).parts[:-1]):
            continue
        for setting, host, line in _yaml_urls(_file_text(file)):
            if host in KNOWN_HOSTS:
                record(externals, KNOWN_HOSTS[host], new_entry(KNOWN_HOSTS[host]), file.resolve(), line)
                continue
            keys = [k for k in setting.split(".") if k.lower() not in GENERIC_URL_KEYS]
            config_urls.setdefault(".".join(keys[-2:]) or setting, []).append((host, file, line))
    for setting, hits in config_urls.items():
        hosts = sorted({h for h, _, _ in hits})
        key = hosts[0] if len(hosts) == 1 else setting
        entry = new_entry(key)
        item = externals.setdefault(key, entry)
        item.setdefault("hosts", set()).update(hosts)
        if len(hosts) == 1:
            item.setdefault("settings", set()).add(setting)
        for host, file, line in hits:
            record(externals, key, entry, file.resolve(), line)

    def finish(registry, prefix):
        items = []
        for key, item in sorted(registry.items()):
            hosts = sorted(item.get("hosts") or [])
            technology = item["technology"]
            if len(hosts) > 1:
                technology = ", ".join(hosts[:3]) + (" …" if len(hosts) > 3 else "")
            elif hosts and item.get("settings"):
                technology = "setting " + ", ".join(sorted(item["settings"]))
            items.append({
                "id": f"{prefix}-{slug(key)}",
                "name": key,
                "technology": technology,
                "evidence": item["evidence"],
                "used_by": sorted(item["used_by"]),
                "used_by_components": {c: sorted(v) for c, v in sorted(item["used_by_components"].items())},
                "used_by_code": {
                    c["id"]: sorted({c["code_components"]["_files"][f] for f in item.get("files", ()) if f in c["code_components"]["_files"]})
                    for c in runnable
                    if c.get("code_components") and any(f in c["code_components"]["_files"] for f in item.get("files", ()))
                },
            })
        return items

    # Inside each container: packages/namespaces of its modules (JVM, C#, Go).
    for container in runnable:
        module_dirs = {}
        for node, info in container["components"]["nodes"].items():
            project = by_id.get(node)
            if project:
                path = project["path"]
                module_dirs[node] = (path.parent if path.is_file() else path).resolve()
        if not module_dirs and container.get("path"):
            module_dirs[container["name"]] = (repo / container["path"]).resolve()
        container["code_components"] = code_facts.code_components(module_dirs, index)

    data_stores = finish(stores, "db")
    external_systems = finish(externals, "ext")

    # Links between containers and stores that the code or config declares.
    store_ids = {s["name"]: s["id"] for s in data_stores}
    relationships = []

    def element_of(service):
        kind, value = compose_map.get(service, (None, None))
        if kind == "store":
            return store_ids.get(value)
        return value["id"] if kind == "container" else None

    services = code_facts.compose_services(index)
    for service in services:
        source = element_of(service["name"])
        for dependency in service["depends_on"]:
            target = element_of(dependency)
            if source and target and source != target:
                relationships.append({
                    "from": source, "to": target, "description": "Depends on",
                    "technology": "", "evidence": [f"{service['file']}:{service['line']}"], "source": "compose depends_on",
                })

    web_apis = [c for c in runnable if "web-api" in c["kind"]]
    host_ports = {}
    for service in services:
        _, value = compose_map.get(service["name"], (None, None))
        if isinstance(value, dict):
            for port in service["ports"]:
                host_ports.setdefault(port.split(":")[0].strip("'\""), value["id"])
    for prefix, target, file, line in code_facts.dev_proxies(repo, index):
        source = owner_container(file)
        port = re.search(r":(\d{2,5})", target)
        backend = host_ports.get(port.group(1)) if port else None
        if backend is None and port:
            backend = next((c["id"] for c in web_apis if port.group(1) in code_facts.declared_ports(repo, (repo / c["path"]).resolve())), None)
        if backend is None and len(web_apis) == 1:
            backend = web_apis[0]["id"]
        if source and backend and source != backend:
            relationships.append({
                "from": source, "to": backend, "description": f"Calls {prefix} (dev-server proxy to {target})",
                "technology": "HTTP", "evidence": [f"{_rel(repo, file)}:{line}"], "source": "dev proxy",
            })

    unique = {}
    for r in relationships:
        key = (r["from"], r["to"], r["source"])
        if key in unique:
            unique[key]["evidence"] += [e for e in r["evidence"] if e not in unique[key]["evidence"]]
        else:
            unique[key] = r
    relationships = list(unique.values())

    deployment = code_facts.deployment(index)  # deployment uses index for indexed traversal
    endpoints = code_facts.endpoints(repo, source_files, owner_container)
    configuration = code_facts.configuration(repo, source_files, owner_container, services, index)

    for container in runnable:
        if container.get("code_components"):
            container["code_components"].pop("_files", None)

    for container in containers:
        modules = [by_id[n]["path"] for n in (container.get("components") or {}).get("nodes", {}) if n in by_id]
        container["inventory"] = code_facts.inventory(repo, container, modules, index) if container.get("path") else (
            [container["technology"]] if container.get("technology") else []
        )

    return {
        "repository": repo.name,
        "containers": [
            {
                key: container.get(key)
                for key in ("id", "name", "kind", "technology", "path", "evidence", "components", "code_components", "inventory", "compose_services")
            }
            for container in containers
        ],
        "data_stores": data_stores,
        "external_systems": external_systems,
        "relationships": relationships,
        "endpoints": endpoints,
        "deployment": deployment,
        "configuration": configuration,
    }


if __name__ == "__main__":
    try:
        from scripts.build_graph import build_dependency_graph
    except ImportError:
        from build_graph import build_dependency_graph

    repo_arg = sys.argv[1]
    print(json.dumps(collect_facts(repo_arg, build_dependency_graph(repo_arg)), indent=2, default=str))
