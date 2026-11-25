"""Exercise the tracker CLI and its snapshot publication with deterministic worker samples."""
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import tracker


class TrackerPair(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        subprocess.run(["git", "init", "-q", self.root], check=True)
        self.revisions = []
        for label in ("baseline", "candidate"):
            subprocess.run(["git", "-C", self.root, "-c", "user.name=Test", "-c", "user.email=test@localhost",
                            "commit", "--allow-empty", "-qm", label], check=True)
            self.revisions.append(subprocess.check_output(["git", "-C", self.root, "rev-parse", "HEAD"],
                                                        text=True).strip())
        self.fixture = self.root / "fixture"
        self.fixture.mkdir()
        files = {}
        for name in ("edges.csv", *tracker.run.ENGINES.values()):
            (self.fixture / name).write_bytes(name.encode())
            files[name] = {"sha256": hashlib.sha256(name.encode()).hexdigest()}
        (self.fixture / "fixture.json").write_text(json.dumps({"files": files}))
        self.library = self.root / "duckdb"
        self.library.write_bytes(b"duckdb")
        self.releases = [self.root / label for label in ("baseline", "candidate")]
        self.outputs = [self.root / (release.name + ".json") for release in self.releases]
        for release in self.releases:
            release.write_bytes(release.name.encode())
        self.calls = []

    def worker(self, args, provider, route, block, cases, expected):
        self.calls.append((block, args.extension.name, args.fixture, args.library))
        return {"block": block, "provider": provider, "route": route, "samples": [
            {"case": case, "repetition": repetition, "wall_ms": 1, "cpu_ms": 1}
            for repetition, case in tracker.schedule(cases, block, args.runs)]}

    def run_cli(self, *extra):
        argv = ["tracker.py", "run", "--extension", self.releases[1], "--source-checkout", self.root,
                "--source-revision", self.revisions[1], "--fixture", self.fixture, "--library", self.library,
                "--case", "full_scan_aggregate", "--provider", "ladybug", "--blocks", "2", "--runs", "1", *extra]
        oracle = {"watchlist_groups": [], "expected": {"full_scan_aggregate": [1, "checksum"]}, "edges": 1}
        with (patch.object(sys, "argv", list(map(str, argv))), patch.object(tracker.run, "oracle", return_value=oracle),
              patch.object(tracker.platform, "system", return_value="Linux"),
              patch.object(tracker.platform, "machine", return_value="aarch64"),
              patch.object(tracker, "measure_worker", side_effect=self.worker), redirect_stdout(io.StringIO())):
            tracker.main()

    def pair_args(self):
        return ["--baseline-extension", self.releases[0], "--baseline-revision", self.revisions[0],
                "--baseline-out", self.outputs[0], "--out", self.outputs[1]]

    def test_pair_runs_in_abba_order_and_records_the_measured_identity(self):
        self.run_cli(*self.pair_args())
        self.assertEqual(self.calls, [(i, label, self.fixture, self.library) for i, label in
                                      [(0, "baseline"), (0, "candidate"), (1, "candidate"), (1, "baseline")]])
        baseline, candidate = reports = [json.loads(path.read_text()) for path in self.outputs]
        self.assertNotEqual(baseline["id"], candidate["id"])
        for key in ("pair_id", "host_id", "fixture", "tracker_sha256", "expected", "statements"):
            self.assertTrue(baseline[key])
            self.assertEqual(baseline[key], candidate[key])
        for report, release, revision in zip(reports, self.releases, self.revisions):
            self.assertEqual(report["workspace_head"], revision)
            self.assertEqual(report["binaries"]["extension"], tracker.run.digest(release))
            self.assertEqual(report["summary"][0]["n"], 2)

    def test_describe_matches_single_run_without_timing_queries(self):
        plan_path = self.root / "description.json"
        self.run_cli("--describe", plan_path)
        self.assertEqual(self.calls, [])
        plan = json.loads(plan_path.read_text())
        self.assertNotIn("finished_utc", plan)
        self.assertNotIn("started_utc", plan)
        self.assertNotIn("workers", plan)
        self.assertEqual(plan["summary"], [{"provider": "ladybug", "route": "qw_pgq", "case": "full_scan_aggregate"}])
        self.run_cli("--out", self.outputs[1])
        report = json.loads(self.outputs[1].read_text())
        self.assertNotIn("pair_id", report)
        for key in ("fixture", "expected", "versions", "statements", "workspace_head", "protocol"):
            self.assertEqual(plan[key], report[key])

    def test_incomplete_pair_and_colliding_outputs_are_rejected_before_timing(self):
        with self.assertRaisesRegex(ValueError, "together"):
            self.run_cli("--baseline-extension", self.releases[0])
        with self.assertRaisesRegex(ValueError, "distinct"):
            self.run_cli(*self.pair_args(), "--out", self.outputs[0])
        self.assertEqual(self.calls, [])
        self.assertFalse(any(path.exists() for path in self.outputs))

    def test_failed_worker_does_not_publish_either_release(self):
        def failing_worker(args, provider, route, block, cases, expected):
            raise RuntimeError("fixture worker error")
        self.worker = failing_worker
        with self.assertRaisesRegex(RuntimeError, "fixture worker error"):
            self.run_cli(*self.pair_args())
        self.assertFalse(any(path.exists() for path in self.outputs))
