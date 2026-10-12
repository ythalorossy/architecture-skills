from pathlib import Path
import argparse
import json
import os
import shutil
import sys
import tempfile

# Allow running as a plain script from any directory, not only
# `python -m scripts.analyze_repository` from the skill folder.
SKILL_DIR = Path(__file__).resolve().parent.parent
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from scripts.cli_support import UserError, require_python, run_cli

# Must run before the imports below: they reach python_projects, which needs
# tomllib (3.11+) and would otherwise fail with an opaque ImportError.
require_python()

from scripts.detect_stack import detect_stack
from scripts.scan_repo import scan_repo
from scripts.build_graph import build_dependency_graph, build_groups
from scripts.generate_mermaid import generate_mermaid
from scripts.generate_docs import analyze_graph, generate_report
from scripts.c4_facts import collect_facts
from scripts.render_c4 import render as render_c4
from scripts.code_diagrams import repository_root
from scripts.repo_index import RepoIndex
from scripts.projects import discover_all
from scripts.diagnostics import DiagnosticsCollector

# The fixed-name artifacts of a run. With the `c4-*.mmd` / `c4-*.svg`
# diagrams they are the only files the analyzer ever deletes from the
# output folder; `c4-model.json` and anything the user put there survive.
GENERATED_FILES = frozenset({
    "ArchitectureReport.md",
    "c4-facts.json",
    "dependency-graph.json",
    "dependency-graph.mmd",
    "dependency-graph.svg",
    "repository-scan.json",
    "summary.json",
})


class RepositoryAnalyzer:
    def __init__(self, repo_path: str, output_path: str, no_svg: bool = False,
                 strict: bool = False, timestamp: bool = False):
        self.repo_path = Path(repo_path).resolve()
        self.output_path = Path(output_path).resolve()
        # Every artifact is written here and moved into output_path at the
        # end, so a crash cannot leave half of one run next to half of
        # another. It is a sibling of output_path, at the same depth, so the
        # relative repository_root stored in c4-facts.json resolves from both.
        self._work_path = self.output_path
        self.no_svg = no_svg
        self.strict = strict
        self.timestamp = timestamp
        self._collector: DiagnosticsCollector | None = None
        self._svg_missing_tool = False
        # True when the run found no container at all: an empty result the
        # user has to act on, so the run is degraded even though nothing
        # failed to read or render.
        self._nothing_detected = False

    def _render_svg(self):
        """SVGs are rendered unless --no-svg or C4_SVG=0 turns them off."""
        from scripts import svg_render as _sr
        return not self.no_svg and not _sr.disabled_by_env()

    def _record_svg(self, statuses):
        """
        Report SVG results. A diagram that failed to render (syntax error,
        timeout, tool error) is a warning and makes the run degraded. No
        mmdc or npx at all is not an error: Node.js is optional, and the
        report keeps the Mermaid source. That gets one note instead.
        """
        for stem, info in statuses.items():
            status = info.get("status", "")
            message = info.get("message", "")
            if status == "missing-tool":
                self._svg_missing_tool = True
            elif status not in ("ok", "skipped"):
                text = f"{stem}: {status}" + (f" — {message}" if message else "")
                print(f"WARNING: {text}")
                self._collector.render_warning("svg_render", text, f"{stem}.mmd")

    def run(self):
        self._validate_repository()
        self._prepare_output_folder()

        staging = self._open_staging_folder()
        try:
            self._work_path = staging
            summary = self._collect()
            self._promote(staging)
        finally:
            self._work_path = self.output_path
            shutil.rmtree(staging, ignore_errors=True)

        self._print_summary(summary)

        return summary

    def _open_staging_folder(self):
        """A sibling folder to build the run in. Same parent, so the relative
        path from the output folder back to the repository is unchanged."""
        try:
            return Path(tempfile.mkdtemp(prefix=".architecture-docs-", dir=self.output_path.parent))
        except OSError as ex:
            raise UserError(
                f"cannot create a temporary folder next to the output folder ({ex.strerror}); "
                "pass --output a folder whose parent is writable",
                path=self.output_path.parent,
            )

    def _promote(self, staging):
        """Move the finished run into the output folder.

        Artifacts an earlier run left behind and this one did not produce are
        removed first, so the folder describes one run only. `c4-model.json`
        is the user's file: it is never written back.
        """
        produced = {p.name for p in staging.iterdir() if p.is_file()} - {"c4-model.json"}
        for old in self.output_path.iterdir():
            if old.is_file() and old.name not in produced and self._is_generated(old.name):
                old.unlink()
        for name in sorted(produced):
            os.replace(staging / name, self.output_path / name)

    @staticmethod
    def _is_generated(name):
        """True for a file this script writes, so nothing else is ever deleted."""
        return name in GENERATED_FILES or (
            name.startswith("c4-") and name.endswith((".mmd", ".svg"))
        )

    def _collect(self):
        print(f"Analyzing repository: {self.repo_path}")

        # One walk of the repository for the whole run.
        self._collector = DiagnosticsCollector(root=self.repo_path)
        self._nothing_detected = False
        index = RepoIndex.build(self.repo_path, self._collector)

        # Discover projects once; every step reuses the result.
        discovery = discover_all(self.repo_path, index, self._collector)

        stacks = self._detect_stack(index)
        scan_results = self._scan_repository(index, discovery)
        dependency_graph = self._build_graph(index=index, discovery=discovery)
        groups = build_groups(self.repo_path, index=index, discovery=discovery)

        self._save_json(
            scan_results,
            self._work_path / "repository-scan.json"
        )

        self._save_json(
            dependency_graph,
            self._work_path / "dependency-graph.json"
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

        summary = self._generate_summary(
            stacks,
            scan_results,
            dependency_graph,
            c4=c4,
        )

        summary["c4"] = c4

        self._save_json(
            summary,
            self._work_path / "summary.json"
        )

        return summary

    def _validate_repository(self):
        if not self.repo_path.exists():
            raise UserError(
                "repository folder not found; pass the folder that holds the code",
                path=self.repo_path,
            )

        if not self.repo_path.is_dir():
            raise UserError(
                "expected a repository folder, not a file; pass the folder that holds the code",
                path=self.repo_path,
            )

    def _prepare_output_folder(self):
        if self.output_path.resolve().is_relative_to(SKILL_DIR):
            raise UserError(
                "the output folder is inside the skill folder; run from your repository or pass --output",
                path=self.output_path,
            )
        try:
            self.output_path.mkdir(
                parents=True,
                exist_ok=True
            )
        except FileExistsError:
            raise UserError(
                "the output path is an existing file; pass a folder with --output",
                path=self.output_path,
            )
        except OSError as ex:
            raise UserError(f"cannot create the output folder ({ex.strerror})", path=self.output_path)

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
            groups,
            title=f"{self.repo_path.name} \u00b7 Project dependency graph",
        )

        mermaid_file = self._work_path / "dependency-graph.mmd"
        svg_file = self._work_path / "dependency-graph.svg"

        mermaid_file.write_text(
            mermaid,
            encoding="utf-8"
        )

        # A stale SVG from an earlier run would show the wrong diagram.
        svg_file.unlink(missing_ok=True)

        self._dep_svg_result = None

        if dependency_graph and self._render_svg():
            print("Rendering diagram to SVG...")

            from scripts import svg_render as _sr
            results = _sr.render(
                [("dependency-graph", mermaid_file)],
                self._work_path,
                svg_flag=True,
                env_disabled=False,
            )
            self._dep_svg_result = results[0] if results else None
            if self._dep_svg_result:
                self._record_svg({"dependency-graph": {
                    "status": self._dep_svg_result.status,
                    "message": self._dep_svg_result.message,
                }})
        elif not self._render_svg():
            from scripts import svg_render as _sr
            self._dep_svg_result = _sr.Result("dependency-graph", "skipped", "rendering disabled", 0.0)

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
                if (self._work_path / "dependency-graph.svg").is_file()
                else None
            ),
            timestamp=self.timestamp,
        )

        report_file = (
            self._work_path /
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
        if not facts["containers"]:
            # Nothing at all: no manifest, no source the detectors recognise.
            # Usually a wrong path, a submodule that was never checked out, or
            # an ecosystem the skill does not read.
            message = (
                "no container detected and no project found: nothing in this repository "
                "matched a manifest or an entry point, so the diagrams are empty. Check "
                "that the path is the repository root and that its sources are checked "
                "out, then describe the runnable parts in c4-model.json."
            )
            print(f"WARNING: {message}")
            self._collector.detection("c4_facts", message)
            # The `detection` kind on its own is not degraded (a library-only
            # repository is understood, just not runnable). An empty result is:
            # the run produced nothing to read, and the user must act.
            self._nothing_detected = True
        elif all(c["kind"] == "unknown" for c in facts["containers"]):
            message = (
                "no container detected (nothing with an entry point, framework or compose "
                "service); the whole repository is drawn as one box. Identify the runnable "
                "parts from the code and describe them in c4-model.json."
            )
            print(f"WARNING: {message}")
            self._collector.detection("c4_facts", message)

        self._save_json(
            facts,
            self._work_path / "c4-facts.json"
        )

        print("Drawing C4 diagrams...")

        # The model is the user's file and stays in the output folder; the
        # renderer reads it from the staging copy and never writes it back.
        model_file = self.output_path / "c4-model.json"
        if self._work_path != self.output_path and model_file.is_file():
            shutil.copy(model_file, self._work_path / "c4-model.json")


        # An existing c4-model.json (written by the agent or edited by the user)
        # is kept. On drift (new facts not covered) it is rendered and the
        # unreviewed facts are listed; on invalid (unknown ids, missing
        # elements) it falls back to facts-only.  c4-model.json is never
        # modified.
        result = render_c4(self._work_path, svg=self._render_svg(), collector=self._collector)
        model_status = result["status"]
        model_errors = result["errors"]
        # render() already drew the facts-only model when the model is invalid,
        # and drew the model with an Unreviewed facts section when it drifts.
        drift = [{"message": message} for message in result["drift"]]
        for message in result["drift"]:
            print(f"DRIFT: {message}")

        # validate() hints: things to fix in c4-model.json that are not bad
        # enough to stop the drawing. render_c4.py standalone prints them;
        # without this they would be computed and thrown away here.
        model_warnings = result["warnings"]
        for warning in model_warnings:
            print(f"WARNING: {warning}")
            self._collector.model_warning("render_c4", warning)

        self._record_svg(result.get("svg", {}))
        svg = {}
        if self._dep_svg_result and self._dep_svg_result.status != "skipped":
            svg["dependency-graph"] = {
                "status": self._dep_svg_result.status,
                "message": self._dep_svg_result.message,
            }
        svg.update(result.get("svg", {}))

        return {
            "containers": len(facts["containers"]),
            "data_stores": len(facts["data_stores"]),
            "external_systems": len(facts["external_systems"]),
            "diagrams": result["diagrams"],
            "model": "facts-only" if result["facts_only"] else "c4-model.json",
            "model_errors": model_errors,
            "model_warnings": model_warnings,
            "model_status": model_status,
            "drift": drift,
            "svg": svg,
        }

    def _generate_summary(
        self,
        stacks,
        scan_results,
        dependency_graph,
        c4=None,
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
        degraded = (collector is not None and collector.degraded) or self._nothing_detected
        status = "degraded" if degraded else "ok"

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

        if self._svg_missing_tool:
            print(
                "NOTE: SVGs not rendered: neither mmdc nor npx is on PATH. The report "
                "shows the Mermaid source instead. Install Node.js 22.13+ (and optionally "
                "@mermaid-js/mermaid-cli) for images."
            )

        # One line saying the run needs attention, with the first causes.
        if summary["status"] == "degraded":
            n_warnings = len(summary.get("warnings") or [])
            n_skipped = len(summary.get("skipped_files") or [])
            model_status = c4.get("model_status", "ok")
            print(
                f"DEGRADED: {n_warnings} warning(s), {n_skipped} skipped file(s), "
                f"model {model_status} — see summary.json"
            )
            for w in (summary.get("warnings") or [])[:3]:
                msg = w.get("message") or ""
                path = w.get("path") or ""
                print(f"  warning: {msg} ({path})")
            for sf in (summary.get("skipped_files") or [])[:3]:
                print(f"  skipped: {sf['path']} ({sf.get('reason', '')})")


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
            "Skip SVG rendering; the report then shows the Mermaid source. "
            "C4_SVG=0 in the environment does the same."
        ),
    )

    parser.add_argument(
        "--svg",
        action="store_true",
        # Accepted so scripts written for 3.3.0-3.3.2 keep working; SVGs are
        # rendered by default again.
        help=argparse.SUPPRESS,
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
            "Exit with code 2 when the run is degraded: a file that could not be read "
            "or parsed, a diagram that failed to render, or an invalid c4-model.json. "
            "By default a degraded run exits 0."
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
