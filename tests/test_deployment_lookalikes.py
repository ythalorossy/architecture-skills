"""Deployment detection on a repository full of files that only look the part.

Everything in `deploy_lookalike` is either real deployment configuration or a
file named like some. A detector that matches on the name alone cannot tell
`notes/Dockerfile.md` from `Dockerfile.api`, or a service's own `app.yaml`
from Google App Engine's, and reports documentation as infrastructure.

Both halves are asserted together on purpose: a fixture that proves there are
no false positives proves nothing if the detectors stopped finding anything.
"""
import unittest
from pathlib import Path

from helpers import SKILL  # noqa: F401  -- sets up sys.path so `scripts` is importable

from scripts import code_facts
from scripts.repo_index import RepoIndex

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "repos" / "deploy_lookalike"


class DeploymentLookalikeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.found = code_facts.deployment(RepoIndex.build(FIXTURE))

    def _files(self, key):
        return sorted(entry["file"] for entry in self.found[key])

    # ---------- the real configuration is still found ----------

    def test_the_helm_chart_and_the_terraform_root_are_found(self):
        self.assertEqual(
            sorted((p["tool"], p["file"]) for p in self.found["platforms"]),
            [("Helm chart", "deploy/chart/Chart.yaml"), ("Terraform", "infra/main.tf")],
        )

    def test_the_real_dockerfile_is_found(self):
        self.assertEqual(self._files("dockerfiles"), ["Dockerfile.api"])

    def test_the_workflow_and_the_manifest_are_found(self):
        self.assertEqual([(c["tool"], c["file"]) for c in self.found["ci"]],
                         [("GitHub Actions", ".github/workflows/ci.yml")])
        self.assertEqual([(k["kind"], k["name"]) for k in self.found["kubernetes"]],
                         [("Deployment", "svc")])

    # ---------- the look-alikes are not ----------

    def test_prose_about_helm_and_terraform_is_not_a_deployment_target(self):
        named = " ".join(self._files("platforms"))
        self.assertNotIn("docs/deployment", named)

    def test_a_tf_file_that_is_not_the_root_module_is_not_terraform(self):
        # Only main.tf names a Terraform root; variables.tf and outputs.tf
        # belong to one and would report the same stack twice.
        self.assertNotIn("infra/terraform/variables.tf", self._files("platforms"))
        self.assertNotIn("infra/terraform/outputs.tf", self._files("platforms"))

    def test_a_manifest_of_an_unknown_kind_is_not_kubernetes(self):
        # apiVersion and kind, but ReportSchedule is somebody's own CRD.
        self.assertEqual([k["file"] for k in self.found["kubernetes"]], ["k8s/deploy.yaml"])

    def test_documentation_named_like_a_dockerfile_is_not_one(self):
        self.assertNotIn("notes/Dockerfile.md", self._files("dockerfiles"))

    def test_a_service_config_called_app_yaml_is_not_google_app_engine(self):
        self.assertNotIn("notes/app.yaml", self._files("platforms"))

    def test_a_file_called_template_yaml_is_not_an_aws_sam_template(self):
        self.assertNotIn("notes/template.yaml", self._files("platforms"))


if __name__ == "__main__":
    unittest.main()
