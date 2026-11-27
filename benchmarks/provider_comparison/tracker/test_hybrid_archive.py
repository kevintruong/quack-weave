"""Keep verified Hybrid Query measurements with the existing benchmark attempt."""
from hashlib import sha256
import io
import json
import unittest
import zipfile

import archive
from ci import WORKLOAD_HASHES


class HybridArchive(unittest.TestCase):
    sha = 'a' * 40
    workload = 'micro_creator_selective'

    def attempt(self, change=None):
        fixture = {"source_sha256": "1" * 64, "modulus": 1, "files": {"edges.csv": {"sha256": "8" * 64}}}
        hybrid_fixture = {"source_sha256": "1" * 64, "modulus": 32, "files": {"edges.csv": {"sha256": "9" * 64}}}
        binaries = {"extension": "2" * 64, "duckdb_library": "3" * 64}
        snapshot = {"workspace_head": self.sha, "id": "ordinary", "fixture": fixture, "binaries": binaries}
        case = {"case_id": self.workload, "case_revision": 1, "scale": "mod32",
                **dict.fromkeys(WORKLOAD_HASHES, "4" * 64)}
        worker = {"provider": "ladybug", "route": "qw_pgq", "block": 0}
        sequence = [{"case": self.workload, "repetition": 0}]
        schedule = [{**worker, "sequence": sequence}]
        digest = sha256(json.dumps(schedule, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        hybrid = {"workspace_head": self.sha, "id": "hybrid", "fixture": hybrid_fixture, "binaries": dict(binaries),
                  "summary": [{"case": self.workload}], "statements": {self.workload: "SELECT 1"},
                  "workload_evidence": {self.workload: case}, "schedule_sha256": digest,
                  "workload_schedule": schedule, "workers": [{**worker, "samples": sequence}],
                  "micro_sqllogic": {"checks": {name: "5" * 64 for name in
                      ("micro_results.test", "micro_snapshot.test", "workload_snapshot.test")}}}
        if change:
            change(hybrid)
        snapshot["hybrid_smoke_snapshot"] = hybrid
        with io.BytesIO() as output:
            with zipfile.ZipFile(output, "w") as bundle:
                for name, item in (("record", {"commit": self.sha, "status": "baseline"}), ("snapshot", snapshot)):
                    bundle.writestr(f"{self.sha}/{name}.json", json.dumps(item))
            return dict(archive.records(output.getvalue(), "main", 4, 1, self.sha))

    def test_extracts_hybrid_snapshot_for_history_queries(self):
        files = self.attempt()
        prefix = f"main/{self.sha}/4-1/"
        self.assertEqual(json.loads(files[prefix + "hybrid_snapshot.json"])["id"], "hybrid")
        self.assertNotIn("hybrid_smoke_snapshot", json.loads(files[prefix + "snapshot.json"]))

    def test_rejects_wrong_hybrid_artifact_or_missing_sql_logic_receipt(self):
        for change in (lambda x: x["binaries"].update(extension="6" * 64),
                       lambda x: x["micro_sqllogic"]["checks"].pop("workload_snapshot.test"),
                       lambda x: x["fixture"].update(source_sha256="7" * 64)):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "Hybrid Query"):
                self.attempt(change)
