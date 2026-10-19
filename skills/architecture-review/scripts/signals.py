"""Detectors that turn a repository plus its c4 facts into review signals.

A signal is a fact the model should weigh, not a finding: it says what the
code or config shows and where (`file:line`), never why it matters. Judging
that is the review's job. Detectors cover only what c4-facts.json does not
already hold, and never put a secret's value in a signal.

Each detector takes a `Context` and returns a list of `Signal`s. `DETECTORS`
runs them in lens order.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from scripts.repo_scan import line_of

MAX_LOCATIONS = 8

SECRET_NAME = re.compile(
    r"(?i)secret|passw(?:or)?d|token|api[_-]?key|private[_-]?key|credential|signing[_-]?key|auth[_-]?key"
)
PLACEHOLDER_START = ("$", "{", "<", "%")


@dataclass(frozen=True)
class Signal:
    lens: str
    kind: str
    summary: str
    locations: tuple = ()
    confidence: str = "high"
    containers: tuple = ()
    detail: dict = field(default_factory=dict)

    def to_dict(self, signal_id):
        shown = list(self.locations[:MAX_LOCATIONS])
        detail = dict(self.detail)
        if len(self.locations) > MAX_LOCATIONS:
            detail["locations_total"] = len(self.locations)
        return {
            "id": signal_id,
            "lens": self.lens,
            "kind": self.kind,
            "summary": self.summary,
            "confidence": self.confidence,
            "locations": shown,
            "containers": list(self.containers),
            "detail": detail,
        }


@dataclass
class Context:
    repo: object
    facts: dict
    files: list
    directories: set

    @property
    def containers(self):
        return self.facts.get("containers") or []

    @property
    def compose(self):
        return (self.facts.get("deployment") or {}).get("compose") or []

    def root_of(self, container):
        """The container's folder, repo-relative; '' when it is the repo root."""
        path = PurePosixPath(str(container.get("path") or "").replace("\\", "/"))
        if path.suffix:
            path = path.parent
        text = path.as_posix()
        return "" if text == "." else text

    def container_for(self, rel):
        """The id of the container whose folder holds `rel` (longest folder wins), or None."""
        best, best_len = None, -1
        for container in self.containers:
            root = self.root_of(container)
            inside = root == "" or rel == root or rel.startswith(root + "/")
            if inside and len(root) > best_len:
                best, best_len = container.get("id"), len(root)
        return best

    def containers_of(self, locations):
        found = []
        for location in locations:
            container = self.container_for(location.rsplit(":", 1)[0])
            if container and container not in found:
                found.append(container)
        return tuple(found)


def _loc(rel, line):
    return f"{rel}:{line}"


# ---------- security ----------

_ENV_DEFAULT_PATTERNS = (
    # os.environ.get("NAME", "default") / os.getenv(...), possibly split over lines
    re.compile(r"""(?:os\.environ\.get|os\.getenv)\(\s*["']([A-Za-z_][\w.]*)["']\s*,\s*["']([^"']*)["']"""),
    # process.env.NAME || "default" / ?? "default"
    re.compile(
        r"""process\.env(?:\.([A-Za-z_]\w*)|\[\s*["']([^"']+)["']\s*\])\s*(?:\|\||\?\?)\s*["']([^"']+)["']"""),
    # Spring-style ${name:default}
    re.compile(r"""\$\{([\w.\-]+):([^}]+)\}"""),
)
_LITERAL_ASSIGNMENT = re.compile(
    r"""(?m)^\s*(?:export\s+|const\s+|let\s+|var\s+|final\s+|static\s+|private\s+|public\s+)*"""
    r"""([A-Za-z_]\w*)\s*[:=]\s*["']([^"'\n]{4,})["']"""
)


_NOT_SECRETS = {"true", "false", "null", "none", "yes", "no", "same-origin", "include", "omit", "cors", "no-cors"}
# A value that names a variable rather than holding a secret: AUTH_TOKEN, APIKEY. Not an uppercase hex key such as
# 3F9A0C...: that has digits and no underscore, and is exactly what a committed secret looks like.
_NAME_LIKE = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+|[A-Z]{2,}")
# Values a template or sample puts where the real secret goes.
_PLACEHOLDER = re.compile(
    r"(?i)^(?:your|my|enter|insert|replace)[\w\-]*$|placeholder|example|sample|dummy|^x{3,}$|^\.+$|^\[[^\]]*\]$")
_HASH_COMMENT_SUFFIXES = (".py", ".rb", ".yml", ".yaml", ".toml", ".properties", ".env", ".cfg", ".conf", ".ini")


def _comment_starts(rel):
    """How a line comment begins in this kind of file. `//` opens an .npmrc entry, not a comment."""
    name = rel.rsplit("/", 1)[-1].lower()
    if name.startswith((".npmrc", ".yarnrc", ".pypirc", ".env")) or name.endswith(_HASH_COMMENT_SUFFIXES):
        return ("#", ";")
    if name.endswith((".xml", ".config")):
        return ("<!--",)
    if name.endswith(".sql"):
        return ("--",)
    return ("//", "/*", "*")


def _commented(text, offset, rel):
    """True when the line holding `offset` is a comment, so the setting on it is not live."""
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", start)
    return text[start:end if end != -1 else len(text)].lstrip().startswith(_comment_starts(rel))


def _real_value(name, value):
    """False for templating, flags, plain URLs, and values that only name something."""
    value = value.strip().strip("\"'")
    if len(value) < 4 or value.startswith(PLACEHOLDER_START) or " " in value:
        return False
    if value.lower() in _NOT_SECRETS or re.fullmatch(r"[\d.:]+", value):
        return False
    if len(re.findall(r"[A-Za-z0-9]", value)) < 4:
        return False
    if _NAME_LIKE.fullmatch(value) or value.lower() in name.lower() or _PLACEHOLDER.search(value):
        return False
    if re.match(r"(?i)https?://", value) and "@" not in value:
        return False  # an endpoint, not a credential; credentials inside a URL are another detector's job
    return True


_JSON_PAIR = re.compile(r"""(?m)["']?([A-Za-z_][\w.\-]*)["']?\s*:\s*["']([^"'\n]{4,})["']""")
_YAML_PLAIN = re.compile(r"""(?m)^[ \t]*([A-Za-z_][\w.\-]*)[ \t]*:[ \t]+([^\s#"'{}\[\]&*|>][^\n#]*?)[ \t]*$""")
_INI_PAIR = re.compile(r"""(?m)^[ \t]*(?:export[ \t]+)?([^\s=#;\[]+?)[ \t]*[=:][ \t]*(\S[^\n]*?)[ \t]*$""")
_RC_PAIR = re.compile(r"""(?m)^[ \t]*([^\s=#;]+)[ \t]*=[ \t]*(\S[^\n]*?)[ \t]*$""")
_XML_ADD = re.compile(r'<add\s+key="([^"]+)"\s+value="([^"]*)"')
_INI_SUFFIXES = (".ini", ".cfg", ".conf", ".properties", ".env")
_RC_NAMES = (".npmrc", ".yarnrc", ".pypirc")


def _json_pairs(text):
    """(dotted path, value, offset) for every string value in a JSON document; None if it does not parse."""
    try:
        document = json.loads(text)
    except ValueError:
        return None
    pairs, cursor = [], 0

    def walk(node, path):
        nonlocal cursor
        items = node.items() if isinstance(node, dict) else enumerate(node) if isinstance(node, list) else ()
        for key, value in items:
            here = f"{path}.{key}" if path else str(key)
            if isinstance(value, str) and isinstance(key, str):
                needle = re.compile(rf'"{re.escape(key)}"\s*:\s*{re.escape(json.dumps(value))}')
                m = needle.search(text, cursor) or needle.search(text)
                offset = m.start() if m else 0
                cursor = m.end() if m else cursor
                pairs.append((here, value, offset))
            else:
                walk(value, here)

    walk(document, "")
    return pairs


def _config_hits(f):
    """(name, value, offset) pairs a config file sets, in whatever format it is written."""
    name = f.rel.rsplit("/", 1)[-1].lower()
    if name.endswith(".json"):
        pairs = _json_pairs(f.text)
        if pairs is not None:
            return pairs
        return [(m.group(1), m.group(2), m.start()) for m in _JSON_PAIR.finditer(f.text)]
    if name.startswith(_RC_NAMES):
        return [(re.split(r"[/:.]", m.group(1))[-1] or m.group(1), m.group(2), m.start())
                for m in _RC_PAIR.finditer(f.text)]
    if name.endswith((".yml", ".yaml")):
        return [(m.group(1), m.group(2), m.start())
                for pattern in (_JSON_PAIR, _YAML_PLAIN) for m in pattern.finditer(f.text)]
    if name.endswith(_INI_SUFFIXES) or name.startswith(".env"):
        return [(m.group(1), m.group(2), m.start()) for m in _INI_PAIR.finditer(f.text)]
    if name.endswith((".config", ".xml")):
        return [(m.group(1), m.group(2), m.start()) for m in _XML_ADD.finditer(f.text)]
    return []


def detect_secret_defaults(ctx):
    """Secret-named variables and settings that carry a hardcoded value, in source or config."""
    found = {}
    for f in ctx.files:
        if f.is_test:
            continue
        hits = []
        for pattern in _ENV_DEFAULT_PATTERNS:
            for m in pattern.finditer(f.text):
                groups = [g for g in m.groups() if g is not None]
                hits.append((groups[0], groups[-1], m.start(), "env-default"))
        if f.is_source:
            for m in _LITERAL_ASSIGNMENT.finditer(f.text):
                hits.append((m.group(1), m.group(2), m.start(), "literal"))
        else:
            hits += [(key, value, offset, "config") for key, value, offset in _config_hits(f)]
        for name, value, offset, form in hits:
            if SECRET_NAME.search(name) and _real_value(name, value) and not _commented(f.text, offset, f.rel):
                entry = found.setdefault(_group(name), {"locations": [], "forms": set(), "settings": set()})
                location = _loc(f.rel, line_of(f.text, offset))
                if location not in entry["locations"]:
                    entry["locations"].append(location)
                entry["forms"].add(form)
                entry["settings"].add(name.upper())

    signals = []
    for name, entry in sorted(found.items()):
        locations = tuple(entry["locations"])
        detail = {"variable": name, "forms": sorted(entry["forms"])}
        if entry["settings"] != {name}:
            detail["settings"] = sorted(entry["settings"])[:MAX_LOCATIONS]
        signals.append(Signal(
            lens="security", kind="secret-default",
            summary=f"{name} has a hardcoded value or default in source or config",
            locations=locations, containers=ctx.containers_of(locations),
            detail=detail,
        ))
    return signals


def _group(name):
    """One signal per kind of setting: CARRIERS.KAISER.PASSWORD and CARRIERS.MODA.PASSWORD are CARRIERS.*.PASSWORD."""
    parts = name.upper().split(".")
    return f"{parts[0]}.*.{parts[-1]}" if len(parts) >= 3 else name.upper()


_URL_CREDENTIAL = re.compile(r"""\b([a-z][a-z0-9+.\-]*)://([^\s:/@'"`<>]+):([^\s@'"`<>/]+)@""")
_KV_PASSWORD = re.compile(r"""(?i)(?:^|[;"'\s])(?:password|pwd)\s*=\s*([^;"'\s<>]+)""")
_KV_CONNECTION = re.compile(r"""(?i)\b(?:server|host|data source|user id|uid|username|database|initial catalog)\s*=""")
_WEAK_PASSWORDS = {"password", "pass", "passwd", "secret", "changeme", "example", "user", "test"}


def _placeholder(password):
    return (password.startswith(PLACEHOLDER_START) or "${" in password or "{{" in password
            or "*" in password or "%" in password or "$(" in password or bool(_PLACEHOLDER.search(password)))


def detect_credentials_in_urls(ctx):
    """Connection strings that embed a password: URL form (scheme://user:pass@host) or key=value form
    (Host=...;Password=...), in source, compose or config files."""
    locations, schemes, weak = [], set(), True
    for f in ctx.files:
        if f.is_test:
            continue
        for m in _URL_CREDENTIAL.finditer(f.text):
            password = m.group(3)
            if _placeholder(password) or _commented(f.text, m.start(), f.rel):
                continue
            locations.append(_loc(f.rel, line_of(f.text, m.start())))
            schemes.add(m.group(1).lower())
            weak = weak and password.lower() in _WEAK_PASSWORDS
        offset = 0
        for line in f.text.splitlines(keepends=True):
            if _KV_CONNECTION.search(line) and not _commented(line, 0, f.rel):
                for m in _KV_PASSWORD.finditer(line):
                    password = m.group(1)
                    if _placeholder(password):
                        continue
                    locations.append(_loc(f.rel, line_of(f.text, offset)))
                    schemes.add("key=value")
                    weak = weak and password.lower() in _WEAK_PASSWORDS
            offset += len(line)
    if not locations:
        return []
    locations = tuple(dict.fromkeys(locations))
    return [Signal(
        lens="security", kind="credentials-in-url",
        summary="Connection strings embed a password",
        locations=locations, confidence="low" if weak else "high",
        containers=ctx.containers_of(locations),
        detail={"schemes": sorted(schemes), "files": len({loc.rsplit(":", 1)[0] for loc in locations})},
    )]


_AUTH_MARKERS = re.compile(
    r"(?i)authenticat|authoriz|login_required|\bjwt\b|oauth|bearer|passport|@PreAuthorize|\[Authorize|"
    r"permission_classes|Depends\(\s*get_current|api[_-]?key|HTTPBasic|security\("
)


def detect_auth_markers_absent(ctx):
    """Containers that serve endpoints but show no authentication or authorization marker."""
    signals = []
    endpoints = ctx.facts.get("endpoints") or []
    for container in ctx.containers:
        cid = container.get("id")
        own = [e for e in endpoints if e.get("container") == cid]
        if not own:
            continue
        sources = [f for f in ctx.files if f.is_source and not f.is_test and ctx.container_for(f.rel) == cid]
        if any(_AUTH_MARKERS.search(f.text) for f in sources):
            continue
        sample = sorted(f"{e.get('method', '')} {e.get('path', '')}".strip() for e in own)[:5]
        first_per_file = {}
        for e in own:
            first_per_file.setdefault(e.get("file", ""), e.get("line", 1))
        signals.append(Signal(
            lens="security", kind="auth-markers-absent",
            summary=f"{cid} serves {len(own)} endpoint(s) and no authentication marker appears in its code",
            locations=tuple(_loc(file, line) for file, line in first_per_file.items()),
            confidence="low", containers=(cid,),
            detail={"endpoints": len(own), "sample": sample},
        ))
    return signals


_DATASTORE_IMAGE = re.compile(
    r"(?i)(?:^|/)(postgres|mysql|mariadb|mongo|redis|elasticsearch|opensearch|rabbitmq|memcached|kafka|cassandra|"
    r"mssql|sqlserver|couchdb|influxdb|clickhouse)")


def _published(port):
    if isinstance(port, dict):
        return bool(port.get("published")) and port.get("host_ip") not in ("127.0.0.1", "localhost", "::1")
    parts = str(port).split(":")
    if len(parts) == 1:
        return False
    return not (len(parts) == 3 and parts[0] in ("127.0.0.1", "localhost", "::1"))


def _service_line_of(ctx, service, needle):
    """Line of `needle` inside a compose service's block; the service's own line if it is not found."""
    start = service.get("line", 1)
    for f in ctx.files:
        if f.rel != service.get("file"):
            continue
        lines = f.text.splitlines()
        if not 1 <= start <= len(lines):
            break
        indent = len(lines[start - 1]) - len(lines[start - 1].lstrip())
        for number in range(start + 1, len(lines) + 1):
            line = lines[number - 1]
            if line.strip() and not line.lstrip().startswith("#") and len(line) - len(line.lstrip()) <= indent:
                break  # the next service begins
            if needle in line:
                return number
        break
    return start


def detect_published_datastore_ports(ctx):
    """Compose data stores whose port is published on the host."""
    exposed = [
        s for s in ctx.compose
        if _DATASTORE_IMAGE.search(s.get("image") or "") and any(_published(p) for p in s.get("ports") or [])
    ]
    if not exposed:
        return []
    locations = []
    for service in exposed:
        port = next(str(p) for p in service.get("ports") or [] if _published(p))
        locations.append(_loc(service.get("file", ""), _service_line_of(ctx, service, port)))
    return [Signal(
        lens="security", kind="datastore-port-published",
        summary="A data store's port is published on the host: " + ", ".join(s["name"] for s in exposed),
        locations=tuple(locations),
        detail={"services": [s["name"] for s in exposed]},
    )]


# ---------- data ----------

_MODEL_PATTERNS = (
    re.compile(r"\bColumn\s*\(|declarative_base\s*\(|\bdb\.Model\b|\bmodels\.Model\b|\bDeclarativeBase\b|"
               r"\bmapped_column\s*\("),
    re.compile(r":\s*DbContext\b|\bDbSet<"),
    re.compile(r"@Entity\b"),
    re.compile(r"(?m)^\s*model\s+\w+\s*\{"),
)
_MIGRATION_DIRS = {"migrations", "alembic", "migrate", "flyway", "liquibase"}
_MIGRATION_FILES = ("alembic.ini", "flyway.conf", "liquibase.properties")


def detect_models_without_migrations(ctx):
    """ORM models or a Prisma schema with no migration folder or tool config anywhere."""
    if ctx.directories & _MIGRATION_DIRS or any(f.rel.endswith(_MIGRATION_FILES) for f in ctx.files):
        return []
    locations = []
    for f in ctx.files:
        if f.is_test or not (f.is_source or f.rel.endswith(".prisma")):
            continue
        for pattern in _MODEL_PATTERNS:
            m = pattern.search(f.text)
            if m:
                locations.append(_loc(f.rel, line_of(f.text, m.start())))
                break
    if not locations:
        return []
    locations = tuple(locations)
    return [Signal(
        lens="data", kind="models-without-migrations",
        summary=f"{len(locations)} file(s) define persisted models and the repository has no migration folder or tool",
        locations=locations, containers=ctx.containers_of(locations),
        detail={"model_files": len(locations)},
    )]


_CONNECTION_VAR = re.compile(r"(?i)url|uri|dsn|host|database|\bdb\b|redis|mongo|broker|queue|bucket")


def detect_shared_stores(ctx):
    """One data store, or one connection setting, used by more than one container."""
    signals, covered = [], []
    for store in ctx.facts.get("data_stores") or []:
        users = sorted(set(store.get("used_by") or []))
        if len(users) < 2:
            continue
        covered.append(set(users))
        signals.append(Signal(
            lens="data", kind="shared-store",
            summary=f"{store.get('name', store.get('id'))} is used by {len(users)} containers: {', '.join(users)}",
            locations=tuple(store.get("evidence") or ()), containers=tuple(users),
            detail={"store": store.get("id"), "used_by": users},
        ))

    by_service = {}
    for container in ctx.containers:
        for service in container.get("compose_services") or []:
            by_service[service] = container.get("id")
    shared = {}
    for service in ctx.compose:
        for name, value in (service.get("environment") or {}).items():
            if value and ("://" in str(value) or _CONNECTION_VAR.search(name)):
                shared.setdefault((name, str(value)), []).append(service)
    for (name, _value), services in sorted(shared.items()):
        if len(services) < 2:
            continue
        users = {by_service[s["name"]] for s in services if s["name"] in by_service}
        if any(users <= group for group in covered):
            continue
        signals.append(Signal(
            lens="data", kind="shared-store",
            summary=f"{name} has the same value in {len(services)} compose services: "
                    + ", ".join(s["name"] for s in services),
            locations=tuple(_loc(s.get("file", ""), s.get("line", 1)) for s in services),
            containers=tuple(sorted(users)),
            detail={"variable": name, "services": [s["name"] for s in services]},
        ))
    return signals


# ---------- application ----------

def _import_pattern(name):
    py = re.compile(rf"(?m)^\s*(?:from\s+{re.escape(name.replace('-', '_'))}(?:\.|\s+import)"
                    rf"|import\s+{re.escape(name.replace('-', '_'))}(?:\.|\s|,|$))")
    js = re.compile(rf"""(?:from\s*|require\(\s*|import\(\s*|import\s+)["'](?:\.\./)+{re.escape(name)}(?:/|["'])""")
    return py, js


def detect_cross_container_imports(ctx):
    """Code in one container that imports the folder another container owns (Python, JS/TS)."""
    signals = []
    rooted = [(c, ctx.root_of(c)) for c in ctx.containers]
    rooted = [(c, root) for c, root in rooted if root]
    for owner, owner_root in rooted:
        sources = [f for f in ctx.files if f.is_source and not f.is_test
                   and ctx.container_for(f.rel) == owner.get("id")]
        for target, target_root in rooted:
            if target is owner or target_root.startswith(owner_root + "/") or owner_root.startswith(target_root + "/"):
                continue
            py, js = _import_pattern(PurePosixPath(target_root).name)
            locations = []
            for f in sources:
                for pattern in (py, js):
                    for m in pattern.finditer(f.text):
                        locations.append(_loc(f.rel, line_of(f.text, m.start())))
            if locations:
                signals.append(Signal(
                    lens="application", kind="cross-container-import",
                    summary=f"{owner.get('id')} imports code that {target.get('id')} owns ({target_root}/)",
                    locations=tuple(dict.fromkeys(locations)), containers=(owner.get("id"), target.get("id")),
                    detail={"from": owner.get("id"), "to": target.get("id")},
                ))
    return signals


# ---------- infrastructure ----------

_FROM = re.compile(r"(?im)^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)")
_USER = re.compile(r"(?im)^\s*USER\s+(\S+)")
_HEALTHCHECK = re.compile(r"(?im)^\s*HEALTHCHECK\s+(?!NONE\b)\S")


def _dockerfiles(ctx):
    return [f for f in ctx.files if PurePosixPath(f.rel).name.lower().startswith("dockerfile")
            or f.rel.lower().endswith(".dockerfile")]


def _last_stage(text):
    """(line of the final FROM, the text from that line on)."""
    last = None
    for m in _FROM.finditer(text):
        last = m
    if last is None:
        return 1, text
    return line_of(text, last.start()), text[last.start():]


def _probe_files(ctx):
    """The compose or Kubernetes files that define a health probe."""
    return sorted(
        f.rel for f in ctx.files
        if f.rel.endswith((".yml", ".yaml")) and ("healthcheck:" in f.text or "livenessProbe" in f.text
                                                 or "readinessProbe" in f.text)
    )


def detect_missing_healthchecks(ctx):
    """Dockerfiles with no HEALTHCHECK; low confidence when a compose or Kubernetes probe exists."""
    probe_files = _probe_files(ctx)
    covered = bool(probe_files)
    signals = []
    for f in _dockerfiles(ctx):
        if _HEALTHCHECK.search(f.text):
            continue
        line, _stage = _last_stage(f.text)
        location = _loc(f.rel, line)
        signals.append(Signal(
            lens="infrastructure", kind="no-healthcheck",
            summary=f"{f.rel} defines no HEALTHCHECK",
            locations=(location,), containers=ctx.containers_of((location,)),
            confidence="low" if covered else "high",
            detail={"probe_defined_elsewhere": covered, "probe_files": probe_files[:MAX_LOCATIONS]},
        ))
    return signals


def _unpinned(ref):
    if not ref or "$" in ref or ref == "scratch" or "@sha256:" in ref:
        return False
    tag = ref.rsplit("/", 1)[-1].partition(":")[2]
    return tag in ("", "latest")


def detect_unpinned_images(ctx):
    """Base images and compose images with no tag, or the `latest` tag."""
    locations = []
    for f in _dockerfiles(ctx):
        for m in _FROM.finditer(f.text):
            if _unpinned(m.group(1)):
                locations.append(_loc(f.rel, line_of(f.text, m.start())))
    for service in ctx.compose:
        if _unpinned(service.get("image") or ""):
            locations.append(_loc(service.get("file", ""), service.get("line", 1)))
    if not locations:
        return []
    return [Signal(
        lens="infrastructure", kind="unpinned-image",
        summary=f"{len(locations)} image reference(s) have no tag or use `latest`",
        locations=tuple(locations), containers=ctx.containers_of(locations),
    )]


def detect_root_containers(ctx):
    """Dockerfiles whose final stage never sets a non-root USER."""
    signals = []
    for f in _dockerfiles(ctx):
        line, stage = _last_stage(f.text)
        users = _USER.findall(stage)
        if users and users[-1].split(":")[0].lower() not in ("root", "0"):
            continue
        base = (_FROM.findall(f.text) or [""])[-1].lower()
        location = _loc(f.rel, line)
        signals.append(Signal(
            lens="security", kind="runs-as-root",
            summary=f"{f.rel} never switches to a non-root USER",
            locations=(location,), containers=ctx.containers_of((location,)),
            confidence="low" if re.search(r"nonroot|unprivileged|distroless", base) else "high",
            detail={"base_image": base},
        ))
    return signals


DETECTORS = (
    detect_secret_defaults,
    detect_credentials_in_urls,
    detect_auth_markers_absent,
    detect_published_datastore_ports,
    detect_root_containers,
    detect_models_without_migrations,
    detect_shared_stores,
    detect_cross_container_imports,
    detect_missing_healthchecks,
    detect_unpinned_images,
)
