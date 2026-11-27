"""Check that the workload manifest resolves only the declared local inputs."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import workload_manifest as workloads


class WorkloadManifestTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory(prefix="qw-workload-paths-")
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name).resolve() / "repo"
        self.manifest = self.root / "hybrid_workloads.json"
        self.document = json.loads(workloads.MANIFEST.read_text(encoding="utf-8"))
        self.case = self.document["cases"][0]
        for case in self.document["cases"]:
            for ref in case["sql_logic_refs"]:
                self.copy_path(ref["path"])
            if "tiny_fixture" in case:
                self.copy_path(case["tiny_fixture"]["path"])
        patches = patch.multiple(workloads, ROOT=self.root, MANIFEST=self.manifest)
        patches.start()
        self.addCleanup(patches.stop)

    def copy_path(self, relative):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(workloads.ROOT / relative, target)

    def load(self):
        self.manifest.write_text(json.dumps(self.document), encoding="utf-8")
        return workloads.load_manifest()

    def test_rejects_absolute_fixture_path(self):
        tiny = self.case["tiny_fixture"]
        tiny["path"] = str(self.root / tiny["path"])
        with self.assertRaisesRegex(ValueError, "path"):
            self.load()

    def test_rejects_parent_traversal_in_sqllogic_reference(self):
        self.case["sql_logic_refs"][0]["path"] = "test/stabilization/sqllogic/../sqllogic/hybrid_creator_selective.test"
        with self.assertRaisesRegex(ValueError, "path"):
            self.load()

    def test_rejects_symlink_outside_checkout(self):
        test = self.root / self.case["sql_logic_refs"][0]["path"]
        outside = self.root.parent / test.name
        test.rename(outside)
        test.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "path"):
            self.load()

    def test_rejects_wrong_sqllogic_markers(self):
        self.case["sql_logic_refs"][0]["case_ids"] = ["hybrid_creator.unregistered"]
        with self.assertRaisesRegex(ValueError, "case markers"):
            self.load()

    def test_rejects_wrong_tiny_row_types_even_if_digest_matches(self):
        tiny = self.case["tiny_fixture"]
        path = self.root / tiny["path"]
        fixture = json.loads(path.read_text(encoding="utf-8"))
        fixture["people"][0][1] = "not an integer"
        path.write_text(json.dumps(fixture), encoding="utf-8")
        tiny["logical_sha256"] = workloads.canonical_sha256(fixture)
        case = self.load()[self.case["case_id"]]
        with self.assertRaisesRegex(ValueError, "people"):
            workloads.read_tiny_fixture(case)


if __name__ == "__main__":
    unittest.main()
