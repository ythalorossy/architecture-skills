"""Entry point for the architecture-review skill: gather evidence, do not judge.

`collect(repo, facts_path)` reads the c4-facts.json that c4-diagrams wrote,
scans the repository for the signals in `signals.py`, and returns the
evidence document. The CLI writes it as `review-evidence.json` beside the
c4 facts. The review itself, `ArchitectureReview.md`, is written by the
agent from this file and the code it points to; nothing here ranks or
words a finding.
"""
import argparse
import fnmatch
import json
import os
import sys
from pathlib import Path

# Allow running as a plain script from any directory, not only
# `python -m scripts.collect_evidence` from the skill folder.
SKILL_DIR = Path(__file__).resolve().parent.parent
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))
from scripts.cli_support import UserError, require_python, run_cli

# Must run before the imports below: they use 3.10+ syntax.
require_python()

from scripts.repo_scan import directory_names, list_files, text_files
from scripts.signals import DETECTORS, Context

EVIDENCE_FILE = "review-evidence.json"
SCHEMA = 1
ID_PREFIX = {"security": "sec", "data": "dat", "application": "app", "infrastructure": "inf"}
LENS_ORDER = ("security", "data", "application", "infrastructure")
NOT_CHECKED = [
    "Everything here is static: no running system, network or database was inspected.",
    "Only files git tracks, or would track, are scanned; gitignored build output is skipped.",
    "Secrets are matched by name in source and in JSON, YAML, INI, .env, .npmrc and XML config; a secret under an "
    "unusual name or in another format is missed.",
    "Authentication is a marker search per container; a gateway or middleware using other names is invisible to it.",
    "Cross-container imports are detected for Python and JS/TS; c4-facts component edges cover JVM, C# and Go.",
    "Migrations are detected by folder or tool-config name, not by whether they match the models.",
    "CI, hosting and Kubernetes files are listed in the context but yield no signals; read them for the "
    "deployment story.",
]
# Matched against the lower-cased repo-relative path.
CI_PATTERNS = (
    "azure-pipelines*.yml", "azure-pipelines*.yaml", "*/azure-pipelines*.yml", "*/azure-pipelines*.yaml",
    ".azure-pipelines/*", ".azuredevops/*", "pipelines/*.yml", "pipelines/*.yaml", ".github/workflows/*",
    ".gitlab-ci.yml", "jenkinsfile", "*/jenkinsfile", "bitbucket-pipelines.yml", ".circleci/*", "buildspec.yml",
    "cloudbuild.yaml", "cloudbuild.yml", ".drone.yml",
)
HOSTING_PATTERNS = (
    "ecosystem.config.*", "procfile", "vercel.json", "netlify.toml", "app.yaml", "fly.toml", "render.yaml",
    "serverless.yml", "serverless.yaml", "*.bicep", "azuredeploy*.json", "web.config", "host.json", "appspec.yml",
    "*.tf", "dockerfile*", "*.dockerfile", "docker-compose*.yml", "docker-compose*.yaml", "compose.yml", "compose.yaml",
    "chart.yaml", "skaffold.yaml",
)
MAX_LISTED = 30
DOC_DIRS = {"docs", "doc", "adr", "adrs", "decisions", "architecture"}
DOC_SUFFIXES = (".md", ".rst", ".adoc")
SKIP_DOC_DIRS = {".git", "node_modules", "architecture-docs", "__pycache__"}
MAX_DOCUMENTS = 30


def load_facts(path):
    path = Path(path)
    if not path.is_file():
        raise UserError("c4-facts.json not found; run the c4-diagrams skill on this repository first", path=str(path))
    try:
        facts = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as ex:
        raise UserError(f"could not read the c4 facts: {ex}", path=str(path)) from ex
    if not isinstance(facts, dict) or not isinstance(facts.get("containers"), list):
        raise UserError("not a c4-facts.json: it has no 'containers' list", path=str(path))
    return facts


def find_documents(repo):
    """Repo-relative paths of the documents a review should compare the code against."""
    repo = Path(repo)
    found = [p.name for p in sorted(repo.iterdir()) if p.is_file() and p.suffix.lower() in DOC_SUFFIXES]
    for folder, dirs, names in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DOC_DIRS)
        rel = Path(folder).relative_to(repo)
        if rel.parts and rel.parts[0].lower() in DOC_DIRS:
            found += [(rel / n).as_posix() for n in sorted(names) if n.lower().endswith(DOC_SUFFIXES)]
    # Shallow documents first, so the cap drops the deepest (plans, archives) and not the top-level docs.
    return sorted(dict.fromkeys(found), key=lambda d: (d.count("/"), d))


def _matching(files, patterns):
    """Files whose path or file name matches one of `patterns`."""
    return [rel for rel in files if any(
        fnmatch.fnmatch(rel.lower(), pattern) or fnmatch.fnmatch(rel.rsplit("/", 1)[-1].lower(), pattern)
        for pattern in patterns)]


def _fact_files(entries):
    return [e.get("file") if isinstance(e, dict) else str(e) for e in entries or [] if e]


def read_model(facts_path):
    """What the c4 model adds to the facts (people, external systems, exclusions, flows), or None without one."""
    path = Path(facts_path).with_name("c4-model.json")
    if not path.is_file():
        return None
    try:
        model = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as ex:
        return {"error": f"c4-model.json could not be read: {ex}"}
    if not isinstance(model, dict):
        return {"error": "c4-model.json is not a JSON object"}
    return {
        "people": [{"id": x.get("id"), "name": x.get("name")} for x in model.get("people") or []],
        "external_systems": [{"id": x.get("id"), "name": x.get("name"), "description": x.get("description")}
                             for x in model.get("external_systems") or []],
        "excluded": [{"id": x.get("id"), "reason": x.get("reason")} for x in model.get("excluded") or []],
        "flows": [x.get("name") or x.get("id") for x in model.get("flows") or []],
    }


def describe_context(facts, repo, facts_path=None):
    deployment = facts.get("deployment") or {}
    files = list_files(repo)
    ci = sorted(set(_matching(files, CI_PATTERNS)) | set(_fact_files(deployment.get("ci"))))
    documents = find_documents(repo)
    return {
        "containers": [
            {"id": c.get("id"), "name": c.get("name"), "kind": c.get("kind"),
             "technology": c.get("technology"), "path": c.get("path")}
            for c in facts.get("containers") or []
        ],
        "data_stores": [
            {"id": s.get("id"), "name": s.get("name"), "technology": s.get("technology")}
            for s in facts.get("data_stores") or []
        ],
        "external_systems": [
            {"id": e.get("id"), "name": e.get("name")} for e in facts.get("external_systems") or []
        ],
        # As detected by c4-diagrams; 0 for a web app usually means its routes were not recognised.
        "endpoints_detected": len(facts.get("endpoints") or []),
        "compose_services": [s.get("name") for s in deployment.get("compose") or []],
        "dockerfiles": [d.get("file") for d in deployment.get("dockerfiles") or []],
        "kubernetes_manifests": len(deployment.get("kubernetes") or []),
        "ci_files": ci[:MAX_LISTED],
        "hosting_files": _matching(files, HOSTING_PATTERNS)[:MAX_LISTED],
        "documents": documents[:MAX_DOCUMENTS],
        "documents_total": len(documents),
        "model": read_model(facts_path) if facts_path else None,
    }


def collect(repo, facts_path):
    repo = Path(repo)
    if not repo.is_dir():
        raise UserError("repository not found", path=str(repo))
    facts = load_facts(facts_path)
    ctx = Context(repo=repo, facts=facts, files=text_files(repo), directories=directory_names(repo))

    raw = [signal for detector in DETECTORS for signal in detector(ctx)]
    raw.sort(key=lambda s: LENS_ORDER.index(s.lens))
    counters, signals = {}, []
    for signal in raw:
        prefix = ID_PREFIX[signal.lens]
        counters[prefix] = counters.get(prefix, 0) + 1
        signals.append(signal.to_dict(f"{prefix}-{counters[prefix]:02d}"))

    return {
        "schema": SCHEMA,
        "repository": repo.resolve().name,
        "facts_file": Path(facts_path).name,
        "context": describe_context(facts, repo, facts_path),
        "signals": signals,
        "not_checked": NOT_CHECKED,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Collect the evidence for an architecture review: writes review-evidence.json.")
    parser.add_argument("repository", help="Path to the repository to review")
    parser.add_argument("--facts", help="c4-facts.json to read "
                        "(default: ./architecture-docs/<repository name>/c4-facts.json)")
    parser.add_argument("--output", help="Folder for review-evidence.json (default: the folder holding the facts)")
    parser.add_argument("--debug", action="store_true", help="Print a traceback on an internal error")
    args = parser.parse_args(argv)

    repo = Path(args.repository)
    facts_path = Path(args.facts) if args.facts else Path("architecture-docs") / repo.resolve().name / "c4-facts.json"
    output = Path(args.output) if args.output else facts_path.parent

    def run():
        evidence = collect(repo, facts_path)
        output.mkdir(parents=True, exist_ok=True)
        target = output / EVIDENCE_FILE
        staging = target.with_name(target.name + ".tmp")
        staging.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        staging.replace(target)
        per_lens = {lens: sum(1 for s in evidence["signals"] if s["lens"] == lens) for lens in LENS_ORDER}
        print(f"Evidence: {len(evidence['signals'])} signal(s) ("
              + ", ".join(f"{lens} {n}" for lens, n in per_lens.items()) + ")")
        print(f"Output File: {target}")

    run_cli(run, debug=args.debug)


if __name__ == "__main__":
    main()
