import json
import tempfile
import unittest
from pathlib import Path

from helpers import write
from scripts import code_diagrams
from scripts.build_graph import build_dependency_graph
from scripts.c4_facts import collect_facts
from scripts.render_c4 import BLOCK_END, BLOCK_START, render

WORKFLOW = '''namespace Api.Workflow;
public interface IWorkflowConductor { bool Change(long id); }
public class WorkflowConductor : IWorkflowConductor
{
    public bool Change(long id) => true;
}
'''


class RenderLevel4Test(unittest.TestCase):
    def test_level4_section_and_structure_rename(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, output = Path(tmp) / "repo", Path(tmp) / "repo" / "architecture-docs" / "repo"
            write(repo, {
                "Api/Api.csproj": '<Project Sdk="Microsoft.NET.Sdk.Web"><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>',
                "Api/Program.cs": "namespace Api;\npublic static class Program { public static void Main() { } }\n",
                "Api/Workflow/Workflow.cs": WORKFLOW,
            })
            output.mkdir(parents=True)
            facts = collect_facts(repo, build_dependency_graph(repo))
            facts["repository_root"] = code_diagrams.repository_root(repo, output)
            (output / "c4-facts.json").write_text(json.dumps(facts, default=str), encoding="utf-8")
            container = facts["containers"][0]["id"]
            model = {
                "system": {"name": "Demo"},
                "containers": [{"id": c["id"], "name": c["name"], "evidence": ["Api/Api.csproj"]} for c in facts["containers"]],
                "code": [{"container": container, "component": "Api::Workflow", "description": "The workflow engine"}],
            }
            (output / "c4-model.json").write_text(json.dumps(model), encoding="utf-8")
            (output / "ArchitectureReport.md").write_text(f"# Report\n\n{BLOCK_START}\n{BLOCK_END}\n", encoding="utf-8")

            result = render(output, svg=False)

            self.assertEqual(result["errors"], [])
            self.assertIn(f"c4-structure-{container}", result["diagrams"])
            self.assertIn(f"c4-code-{container}-api-workflow", result["diagrams"])
            report = (output / "ArchitectureReport.md").read_text(encoding="utf-8")
            self.assertIn("### Level 4: Code", report)
            self.assertIn("The workflow engine", report)
            self.assertIn("> Sources: IWorkflowConductor → `Api/Workflow/Workflow.cs:2`, WorkflowConductor → `Api/Workflow/Workflow.cs:3`", report)
            self.assertIn("code structure", report)
            level4 = (output / f"c4-code-{container}-api-workflow.mmd").read_text(encoding="utf-8")
            # The title joins the renderer options already in the front matter.
            self.assertTrue(level4.startswith('---\ntitle: "'), level4[:80])
            self.assertIn("\nconfig:\n", level4)
