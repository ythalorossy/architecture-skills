from pathlib import Path
import argparse
import json
import sys

# Allow running as a plain script from any directory, not only
# `python -m scripts.analyze_repository` from the skill folder.
SKILL_DIR = Path(__file__).resolve().parent.parent
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from scripts.cli_support import require_python, run_cli

# Must run before the imports below: they reach python_projects, which needs
# tomllib (3.11+) and would otherwise fail with an opaque ImportError.
require_python()

from scripts.detect_stack import detect_stack
from scripts.scan_repo import scan_repo
from scripts.build_graph import build_dependency_graph, build_groups
from scripts.generate_mermaid import generate_mermaid, render_svg
from scripts.generate_docs import analyze_graph, generate_report
from scripts.c4_facts import collect_facts
from scripts.render_c4 import render as render_c4
from scripts.code_diagrams import repository_root
from scripts.repo_index import RepoIndex
from scripts.projects import discover_all
from scripts.diagnostics import DiagnosticsCollector


class RepositoryAnalyzer:
    def __init__(self, repo_path: str, output_path: str, no_svg: bool = False, strict: bool = False, timestamp: bool = False):
        self.repo_path = Path(repo_path).resolve()
        self.output_path = Path(output_path).resolve()
        self.no_svg = no_svg
        self.strict = strict
        self.timestamp = timestamp
        self._collector: DiagnosticsCollector | None = None

    def run(self):
        self._validate_repository()
        self._prepare_output_folder()

        print(f"Analyzing repository: {self.repo_path}")

        # Build the RepoIndex once for the entire run (SPEC-03: one walk per run)
        self._collector = DiagnosticsCollector()
        index = RepoIndex.build(self.repo_path, self._collector)

        # Discover projects once and reuse (SPEC-03: I/O efficiency)
        discovery = discover_all(self.repo_path, index, self._collector)

        stacks = self._detect_stack(index)
        scan_results = self._scan_repository(index, discovery)
        dependency_graph = self._build_graph(index=index, discovery=discovery)
        groups = build_groups(self.repo_path, index=index, discovery=discovery)

        self._save_json(
            scan_results,
            self.output_path / "repository-scan.json"
        )

        self._save_json(
            dependency_graph,
            self.output_path / "dependency-graph.json"
        )

        mermaid = self._generate_mermaid(
            dependency_graph,
            groups
        )

        self._generate_report(
            stacks,
            dependency_graph,
            scan_results,
            groups,
            mermaid
        )

        c4 = self._generate_c4(dependency_graph, index=index, discovery=discovery)

        # Merge diagnostics from the collector into the c4 section
        c4.update(self._collector.summary_dict())

        summary = self._generate_summary(
            stacks,
            scan_results,
            dependency_graph
        )

        summary["c4"] = c4

        self._save_json(
            summary,
            self.output_path / "summary.json"
        )

        self._print_summary(summary)

        return summary

    def _validate_repository(self):
        if not self.repo_path.exists():
            raise FileNotFoundError(
                f"Repository not found: {self.repo_path}"
            )

        if not self.repo_path.is_dir():
            raise NotADirectoryError(
                f"Not a directory: {self.repo_path}"
            )

    def _prepare_output_folder(self):
        self.output_path.mkdir(
            parents=True,
            exist_ok=True
        )

    def _detect_stack(self, index):
        print("Detecting technology stack...")
        return detect_stack(self.repo_path, index)

    def _scan_repository(self, index, discovery):
        print("Scanning repository...")
        scan_results, _ = scan_repo(self.repo_path, index, discovery)
        return scan_results

    def _build_graph(self, index=None, discovery=None):
        print("Building dependency graph...")
        return build_dependency_graph(self.repo_path, index=index, discovery=discovery)

    def _generate_mermaid(self, dependency_graph, groups):
        print("Generating Mermaid diagram...")

        mermaid = generate_mermaid(
            dependency_graph,
            groups
        )

        mermaid_file = self.output_path / "dependency-graph.mmd"
        svg_file = self.output_path / "dependency-graph.svg"

        mermaid_file.write_text(
            mermaid,
            encoding="utf-8"
        )

        # A stale SVG from an earlier run would show the wrong diagram.
        svg_file.unlink(missing_ok=True)

        if dependency_graph:
            print("Rendering diagram to SVG...")

            if not render_svg(mermaid_file, svg_file):
                print(
                    "WARNING: Could not render dependency-graph.svg (needs Node.js "
                    "and @mermaid-js/mermaid-cli). The report keeps the Mermaid block only."
                )

        return mermaid

    def _generate_report(
        self,
        stacks,
        dependency_graph,
        scan_results,
        groups,
        mermaid
    ):
        print("Generating architecture report...")

        report = generate_report(
            project_name=self.repo_path.name,
            stacks=stacks,
            graph=dependency_graph,
            scan=scan_results,
            groups=groups,
            mermaid=mermaid,
            diagram_image=(
                "dependency-graph.svg"
                if (self.output_path / "dependency-graph.svg").is_file()
                else None
            ),
            timestamp=self.timestamp,
        )

        report_file = (
            self.output_path /
            "ArchitectureReport.md"
        )

        report_file.write_text(
            report,
            encoding="utf-8"
        )

    def _generate_c4(self, dependency_graph, index=None, discovery=None):
        print("Collecting C4 facts...")

        facts = collect_facts(self.repo_path, dependency_graph, index=index, discovery=discovery)
        facts["repository_root"] = repository_root(self.repo_path, self.output_path)

        self._save_json(
            facts,
            self.output_path / "c4-facts.json"
        )

        print("Drawing C4 diagrams...")

        # An existing c4-model.json (written by the agent or edited by the user)
        # is kept. On drift (new facts not covered) it is rendered and the
        # unreviewed facts are listed; on invalid (unknown ids, missing
        # elements) it falls back to facts-only.  c4-model.json is never
        # modified.
        result = render_c4(self.output_path, svg=not self.no_svg, collector=self._collector)
        model_errors = result["errors"]
        model_warnings = result.get("warnings") or []
        model_status = "ok"
        drift = []
        if model_errors:
            # Invalid: at least one element or relationship id is unknown.
            result = render_c4(self.output_path, facts_only=True, svg=not self.no_svg, collector=self._collector)
            model_status = "invalid"
        elif model_warnings:
            # Drift: the model is valid but some facts are not yet covered.
            # Re-render with the model and surface the unreviewed facts.
            result = render_c4(self.output_path, svg=not self.no_svg, collector=self._collector, show_drift=True)
            model_status = "drift"
            for w in model_warnings:
                if "not in the model" in w.lower() or "was found in the code" in w.lower():
                    drift.append({"message": w})

        if result["svg_failed"]:
            print(
                "WARNING: Could not render the C4 SVGs (needs Node.js and "
                "@mermaid-js/mermaid-cli). The report keeps the Mermaid blocks only."
            )

        return {
            "containers": len(facts["containers"]),
            "data_stores": len(facts["data_stores"]),
            "external_systems": len(facts["external_systems"]),
            "diagrams": result["diagrams"],
            "model": "facts-only" if result["facts_only"] else "c4-model.json",
            "model_errors": model_errors,
            "model_status": model_status,
            "drift": drift,
        }

    def _generate_summary(
        self,
        stacks,
        scan_results,
        dependency_graph
    ):
        total_dependencies = sum(
            len(v)
            for v in dependency_graph.values()
        )

        facts = analyze_graph(
            dependency_graph,
            scan_results
        )

        collector = self._collector
        status = "degraded" if (collector and collector.degraded) else "ok"

        return {
            "repository": self.repo_path.name,
            "technology_stack": stacks,
            "projects_found": len(
                scan_results.get(
                    "projects",
                    []
                )
            ),
            "folders_found": len(
                scan_results.get(
                    "folders",
                    []
                )
            ),
            "components_found": len(
                dependency_graph
            ),
            "dependencies_found": total_dependencies,
            "test_projects": facts["tests"],
            "orphan_projects": facts["orphans"],
            "duplicate_project_names": facts["duplicates"],
            "unresolved_references": [
                {"from": source, "to": target}
                for source, target in facts["unresolved"]
            ],
            "cycles": facts["cycles"],
            "untested_projects": facts["untested"],
            "dependency_graph_available": bool(dependency_graph),
            "status": status,
            "warnings": collector.warnings() if collector else [],
            "skipped_files": collector.skipped_files() if collector else [],
        }

    def _save_json(
        self,
        data,
        file_path
    ):
        with open(
            file_path,
            "w",
            encoding="utf-8"
        ) as file:
            json.dump(
                data,
                file,
                indent=2
            )

    def _print_summary(
        self,
        summary
    ):
        print("\nAnalysis Complete")
        print("=" * 50)

        print(
            f"Repository: "
            f"{summary['repository']}"
        )

        print(
            f"Technology Stack: "
            f"{', '.join(summary['technology_stack'])}"
        )

        print(
            f"Projects Found: "
            f"{summary['projects_found']}"
        )

        print(
            f"Components Found: "
            f"{summary['components_found']}"
        )

        print(
            f"Dependencies Found: "
            f"{summary['dependencies_found']}"
        )

        for label, key in (
            ("Projects Outside Solutions", "orphan_projects"),
            ("Unresolved References", "unresolved_references"),
            ("Dependency Cycles", "cycles"),
            ("Untested Projects", "untested_projects"),
        ):
            if summary[key]:
                print(f"{label}: {len(summary[key])}")

        if not summary["dependency_graph_available"]:
            print(
                "WARNING: No supported projects found (.NET, Node.js, Python, "
                "Maven, Gradle). Analyze this repository manually."
            )

        c4 = summary["c4"]
        print(
            f"C4: {c4['containers']} container(s), {c4['data_stores']} data store(s), "
            f"{c4['external_systems']} external system(s), {len(c4['diagrams'])} diagram(s) "
            f"from {c4['model']}"
        )

        for error in c4.get("model_errors") or []:
            print(f"C4 MODEL ERROR: {error}")

        print(
            f"Output Folder: "
            f"{self.output_path}"
        )

        # DEGRADED line (SPEC-08: diagnostics channel)
        if summary["status"] == "degraded":
            n_warnings = len(summary.get("warnings") or [])
            n_skipped = len(summary.get("skipped_files") or [])
            model_status = c4.get("model_status", "ok")
            print(
                f"DEGRADED: {n_warnings} warning(s), {n_skipped} skipped file(s), "
                f"model {model_status} — see summary.json"
            )


def default_output_path(repo_path):
    return (
        Path.cwd()
        / "architecture-docs"
        / Path(repo_path).resolve().name
    )


def parse_arguments():
    parser = argparse.ArgumentParser(
        description=(
            "Analyze a repository and "
            "generate architecture "
            "documentation artifacts."
        )
    )

    parser.add_argument(
        "repository",
        help="Path to repository"
    )

    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Output directory (default: "
            "./architecture-docs/<repository name> in the current directory)"
        )
    )

    parser.add_argument(
        "--no-svg",
        action="store_true",
        help=(
            "Skip SVG rendering so the output is byte-identical without "
            "Node.js and @mermaid-js/mermaid-cli (recommended for CI and "
            "golden-file tests)"
        ),
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print the full traceback when an unexpected error occurs",
    )

    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Exit with code 2 when the run is degraded (parse errors, skipped files, "
            "or model drift/invalid).  By default a degraded run exits 0."
        ),
    )

    parser.add_argument(
        "--timestamp",
        action="store_true",
        help=(
            "Include a wall-clock 'Generated On' timestamp in the report. "
            "By default the report has no timestamp so re-runs produce byte-identical output."
        ),
    )

    return parser.parse_args()


def main():
    args = parse_arguments()

    analyzer = RepositoryAnalyzer(
        repo_path=args.repository,
        output_path=args.output or default_output_path(args.repository),
        no_svg=args.no_svg,
        strict=args.strict,
        timestamp=args.timestamp,
    )

    summary = analyzer.run()

    # Exit codes: 0=ok, 1=failure (no artifacts), 2=strict+degraded
    status = summary.get("status", "ok")
    if status == "degraded" and args.strict:
        sys.exit(2)
    # 0 for ok, 0 for degraded (non-strict)
    sys.exit(0)


if __name__ == "__main__":
    # --debug is read from argv here: run_cli needs it before main() parses.
    run_cli(main, debug="--debug" in sys.argv)
