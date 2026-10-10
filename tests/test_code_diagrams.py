import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import write
from scripts import code_diagrams

WORKFLOW = '''namespace Api.Workflow;
public interface IWorkflowConductor { bool Change(long id); }
public abstract class RepositoryBase { }
public class WorkflowConductor : RepositoryBase, IWorkflowConductor
{
    public WorkflowConductor(IClock clock) { }
    public bool Change(long id) => true;
}
public interface IClock { long Now(); }
public class Unrelated { }
'''


def make_repo(root):
    write(root / "repo", {
        "Api/Api.csproj": '<Project Sdk="Microsoft.NET.Sdk.Web"></Project>',
        "Api/Program.cs": "var app = 1;\n",
        "Api/Workflow/Workflow.cs": WORKFLOW,
        "Api/Workflow/WorkflowTests.cs": "public class WorkflowTests { }",
    })


FACTS = {
    "repository_root": "../repo",
    "containers": [{
        "id": "api", "name": "Api", "path": "Api",
        "components": {"nodes": {"Api": {"path": "Api/Api.csproj", "group": "Api"}}, "edges": {"Api": []}},
        "code_components": {"nodes": {"Api::(root)": {}, "Api::Workflow": {}}, "edges": {}},
    }],
}


def model(*code):
    return {"containers": [{"id": "api", "name": "Api"}], "code": list(code)}


class PrepareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        make_repo(self.root)
        self.output = self.root / "out"
        self.output.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def prepare(self, *code, facts=FACTS):
        return code_diagrams.prepare(model(*code), facts, self.output)

    def test_valid_entry_with_types(self):
        errors, warnings, entries = self.prepare(
            {"container": "api", "component": "Api::Workflow", "description": "Workflow", "types": ["WorkflowConductor"]})
        self.assertEqual((errors, warnings), ([], []))
        entry = entries[0]
        self.assertEqual(entry["stem"], "c4-code-api-api-workflow")
        self.assertEqual(entry["title"], "Api · Api::Workflow")
        self.assertEqual(entry["chosen"], ["WorkflowConductor", "IClock", "IWorkflowConductor", "RepositoryBase"])
        self.assertEqual(entry["left_out"], ["Unrelated"])
        self.assertNotIn("WorkflowTests", entry["types"])

    def test_module_component_reads_every_folder(self):
        errors, _, entries = self.prepare({"container": "api", "component": "Api"})
        self.assertEqual(errors, [])
        self.assertIn("WorkflowConductor", entries[0]["types"])

    def test_unknown_container(self):
        errors, _, _ = self.prepare({"container": "web", "component": "Api::Workflow"})
        self.assertIn("not a container", errors[0])

    def test_unknown_component_suggests_close_ids(self):
        errors, _, _ = self.prepare({"container": "api", "component": "Api::Workflw"})
        self.assertIn("did you mean Api::Workflow", errors[0])

    def test_unknown_type_suggests_close_names(self):
        errors, _, _ = self.prepare({"container": "api", "component": "Api::Workflow", "types": ["WorkflowConducter"]})
        self.assertIn("did you mean WorkflowConductor", errors[0])

    def test_missing_fields(self):
        errors, _, _ = self.prepare({"container": "api"})
        self.assertIn("needs a container and a component", errors[0])

    def test_component_without_types_is_a_warning(self):
        errors, warnings, entries = self.prepare({"container": "api", "component": "Api::(root)"})
        self.assertEqual((errors, entries), ([], []))
        self.assertIn("no classes or interfaces", warnings[0])

    def test_more_than_five_entries_warns(self):
        components = ["Api::Workflow", "Api", "Api::Workflow", "Api", "Api::Workflow", "Api"]
        _, warnings, _ = self.prepare(*[{"container": "api", "component": c} for c in components])
        self.assertTrue(any("Level 4 is meant for" in w for w in warnings))

    def test_duplicate_entries(self):
        errors, _, _ = self.prepare({"container": "api", "component": "Api"}, {"container": "api", "component": "Api"})
        self.assertIn("listed twice", errors[0])

    def test_malformed_entries_are_validation_errors(self):
        for item, message in [
            ({"container": "api", "component": "Api", "types": [{"name": "Foo"}]}, "types must be a list of type names"),
            ({"container": "api", "component": "Api", "types": "WorkflowConductor"}, "types must be a list of type names"),
            ({"container": "api", "component": 5}, "needs a container and a component"),
            ({"container": ["api"], "component": "Api"}, "needs a container and a component"),
        ]:
            errors, _, _ = self.prepare(item)
            self.assertEqual(len(errors), 1, item)
            self.assertIn(message, errors[0])

    def test_symlink_outside_the_folder_is_skipped(self):
        shared = self.root / "shared"
        shared.mkdir()
        (shared / "Common.cs").write_text("public class Common { }")
        try:
            (self.root / "repo" / "Api" / "Workflow" / "Common.cs").symlink_to(shared / "Common.cs")
        except OSError:
            self.skipTest("symlinks not available")
        for component in ("Api", "Api::Workflow"):
            errors, _, entries = self.prepare({"container": "api", "component": component})
            self.assertEqual(errors, [])
            self.assertNotIn("Common", entries[0]["types"])

    def test_facts_from_an_older_version(self):
        facts = {k: v for k, v in FACTS.items() if k != "repository_root"}
        errors, _, _ = self.prepare({"container": "api", "component": "Api"}, facts=facts)
        self.assertEqual(errors, ["code: c4-facts.json has no repository_root; re-run analyze_repository.py"])

    def test_no_code_entries_need_no_repository_root(self):
        facts = {k: v for k, v in FACTS.items() if k != "repository_root"}
        self.assertEqual(code_diagrams.prepare({"containers": []}, facts, self.output), ([], [], []))


class RepositoryRootTest(unittest.TestCase):
    def test_relative_with_forward_slashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            output = repo / "architecture-docs" / "repo"
            output.mkdir(parents=True)
            self.assertEqual(code_diagrams.repository_root(repo, output), "../..")

    def test_absolute_when_no_relative_path_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("os.path.relpath", side_effect=ValueError("path is on mount 'D:'")):
                self.assertEqual(code_diagrams.repository_root(tmp, tmp), Path(tmp).resolve().as_posix())


def fake(name, depends_on=(), methods=()):
    return {"name": name, "kind": "class", "bases": [], "interfaces": [], "embeds": [],
            "depends_on": list(depends_on), "methods": list(methods), "values": []}


class SelectTypesTest(unittest.TestCase):
    def test_large_component_draws_the_most_connected(self):
        types = {f"T{i:02}": fake(f"T{i:02}") for i in range(30)}
        types["Hub"] = fake("Hub", depends_on=[f"T{i:02}" for i in range(5)])
        chosen, left_out = code_diagrams.select_types(types)
        self.assertEqual(len(chosen), 12)
        self.assertEqual(chosen[:6], ["Hub", "T00", "T01", "T02", "T03", "T04"])
        self.assertEqual(len(left_out), 19)

    def test_wanted_types_are_capped_too(self):
        types = {f"T{i:02}": fake(f"T{i:02}") for i in range(15)}
        chosen, left_out = code_diagrams.select_types(types, list(types))
        self.assertEqual(len(chosen), 12)
        self.assertEqual(left_out, ["T12", "T13", "T14"])

    def test_wanted_types_come_first_even_when_unconnected(self):
        types = {"A": fake("A", depends_on=["B"]), "B": fake("B"), "C": fake("C")}
        chosen, left_out = code_diagrams.select_types(types, ["C", "A"])
        self.assertEqual(chosen, ["C", "A", "B"])
        self.assertEqual(left_out, [])


def typ(name, kind="class", **fields):
    t = {"name": name, "kind": kind, "file": Path("/repo/src") / f"{name}.cs", "line": 3,
         "bases": [], "interfaces": [], "embeds": [], "depends_on": [], "methods": [], "values": []}
    t.update(fields)
    return t


EXPECTED = """---
config:
  class:
    hideEmptyMembersBox: true
---
classDiagram
    direction TB
    class WorkflowConductor {
        +Change(id) bool
        +Load(id) Task#lt;List#lt;Job#gt;#gt;
    }
    class IClock {
        <<interface>>
        +Now() long
    }
    class IWorkflowConductor {
        <<interface>>
        +Change(id) bool
    }
    class Status {
        <<enum>>
        Ready
        Done
    }
    class RepositoryBase {
        <<external>>
    }
    RepositoryBase <|-- WorkflowConductor
    IWorkflowConductor <|.. WorkflowConductor
    WorkflowConductor ..> IClock
    style WorkflowConductor fill:#85bbf0,stroke:#5d82a8,color:#000000
    style IClock fill:#85bbf0,stroke:#5d82a8,color:#000000
    style IWorkflowConductor fill:#85bbf0,stroke:#5d82a8,color:#000000
    style Status fill:#85bbf0,stroke:#5d82a8,color:#000000
    style RepositoryBase fill:#dbe9f6,stroke:#5d82a8,color:#000000,stroke-dasharray:4 3
"""


class ClassDiagramTest(unittest.TestCase):
    def test_snapshot(self):
        types = {
            "IWorkflowConductor": typ("IWorkflowConductor", "interface", methods=["Change(id) bool"]),
            "WorkflowConductor": typ("WorkflowConductor", bases=["RepositoryBase"], interfaces=["IWorkflowConductor"],
                                     methods=["Change(id) bool", "Load(id) Task<List<Job>>"], depends_on=["IClock"]),
            "IClock": typ("IClock", "interface", methods=["Now() long"]),
            "Status": typ("Status", "enum", values=["Ready", "Done"]),
        }
        chosen = ["WorkflowConductor", "IClock", "IWorkflowConductor", "Status"]
        self.assertEqual(code_diagrams.class_diagram(types, chosen), EXPECTED)

    def test_member_cap_go_returns_and_embedding(self):
        types = {
            "Store": typ("Store", "struct", embeds=["Base"], methods=[f"M{i}() error" for i in range(10)]),
            "Base": typ("Base", "struct", methods=["Get(ctx, id) (*Order, error)"]),
        }
        text = code_diagrams.class_diagram(types, ["Store", "Base"])
        self.assertIn("        +M7() error\n        …(2 more)\n", text)  # parentheses keep it in the methods compartment
        self.assertNotIn("+M8()", text)
        self.assertIn("+Get(ctx, id) *Order, error", text)
        self.assertIn("    Store *-- Base\n", text)

    def test_enum_overflow_stays_with_the_values(self):
        types = {"Big": typ("Big", "enum", values=[f"V{i}" for i in range(10)])}
        self.assertIn("        V7\n        … 2 more\n", code_diagrams.class_diagram(types, ["Big"]))

    def test_many_unconnected_groups_are_laid_out_left_to_right(self):
        types = {}
        for i in range(3):
            types[f"I{i}"] = typ(f"I{i}", "interface")
            types[f"C{i}"] = typ(f"C{i}", interfaces=[f"I{i}"])
        self.assertIn("    direction LR\n", code_diagrams.class_diagram(types, list(types)))
        two = {k: v for k, v in types.items() if k[1] != "2"}
        self.assertIn("    direction TB\n", code_diagrams.class_diagram(two, list(two)))

    def test_generics_with_commas_use_entity_codes(self):
        types = {"A": typ("A", methods=["Map() Task<Dictionary<string, int>>"])}
        self.assertIn("+Map() Task#lt;Dictionary#lt;string, int#gt;#gt;", code_diagrams.class_diagram(types, ["A"]))

    def test_unsafe_names_get_ids_and_labels(self):
        types = {
            "Ação": typ("Ação", interfaces=["note"]),
            "link": typ("link", depends_on=["Ação"]),
        }
        text = code_diagrams.class_diagram(types, ["Ação", "link"])
        self.assertNotIn("class Ação", text)
        # Each 'class <id>' line must have the safe id, not the bare keyword
        for line in text.splitlines():
            if line.startswith("class link"):
                self.assertTrue(line.startswith("class link_") or "[" in line,
                    f"Bare 'class link' found: {line!r}")
            if line.startswith("class note"):
                self.assertTrue(line.startswith("class note_") or "[" in line,
                    f"Bare 'class note' found: {line!r}")
        self.assertIn('["Ação"]', text)
        self.assertIn('["link"]', text)
        self.assertIn('["note"]', text)

    def test_notes(self):
        types = {"A": typ("A"), "B": typ("B")}
        entry = {"types": types, "chosen": ["A"], "left_out": ["B"], "repo": Path("/repo")}
        self.assertEqual(code_diagrams.notes(entry), [
            "Sources: A → `src/A.cs:3`",
            "Not drawn: 1 more type (B)",
        ])
