"""Exercise the tracker CLI and its snapshot publication with deterministic worker samples."""
from contextlib import nullcontext, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, call, patch

import pyarrow as pa

import tracker


class PhaseMeasurements(unittest.TestCase):
    def test_one_bootstrap_per_connection_and_only_warm_engine_samples(self):
        workers = []
        for route in ("direct_cypher", "qw_cypher"):
            for block in (0, 1):
                samples = [{"case": "lookup_miss", "repetition": i, "wall_ms": t, "cpu_ms": 1}
                           for i, t in enumerate((1000, 5, 10))]
                native = [{**s, "engine_ms": t, "start_ns": 0, "end_ns": 10_000_000}
                          for s, t in zip(samples, (1000, 2, 4))]
                workers.append({"block": block, "provider": "ladybug", "route": route, "samples": samples,
                                "setup": {"open_ms": 20, "bootstrap_ms": 20, "prepare_ms": 99},
                                "engine_samples": native})
        row = tracker.summarize(workers)[1]
        self.assertEqual(row["engine_execution"], {"n": 4, "p50_ms": 3, "p95_ms": 4})
        self.assertEqual(row["p50_ms"], 7.5)
        self.assertEqual(row["other_warm_work"]["p50_ms"], 7)
        self.assertEqual(tracker.summarize_bootstrap(workers)[1],
                         {"provider": "ladybug", "route": "qw_cypher", "n": 2, "p50_ms": 20,
                          "p95_ms": 20, "stage_p50_ms": {"open_ms": 20}})

    def test_one_native_event_per_verified_submission(self):
        samples = [{"start_ns": 10, "end_ns": 50}]
        for trace, provider in [("", "ladybug"), ("QW_PHASE 0 100 1 1", "ladybug"),
                                ("QW_RELATE_PHASE 0 0 NaN", "relate")]:
            with self.subTest(trace=trace), self.assertRaises(ValueError):
                tracker.attach_trace(samples, trace, provider)
        tracker.attach_trace(samples, "QW_RELATE_PHASE 2 3 5", "relate")
        self.assertEqual((samples[0]["parse_ms"], samples[0]["plan_ms"], samples[0]["engine_ms"]), (2, 3, 5))


class PreparedWorker(unittest.TestCase):
    def test_live_scan_cannot_keep_returning_the_previous_dialects_result(self):
        parent = MagicMock()
        handle = parent.connection.cursor.return_value.__enter__.return_value
        handle.execute.return_value.fetch_arrow_table.return_value = pa.table({"id": [tracker.run.KEYS[0]]})
        with self.assertRaisesRegex(ValueError, "dialect_gql: expected QW_GQL_SUBSET, observed hit"):
            tracker.lookup.probe_session(parent, tracker.lookup.LIVE)
        handle.adbc_prepare.assert_called_once()

    def test_parameterized_match_prepares_once_for_both_keys_after_selecting_dialect(self):
        parent = MagicMock()
        handle = parent.connection.cursor.return_value.__enter__.return_value
        def fetch():
            key, = handle.execute.call_args.args[1]
            return pa.table({"id": pa.array([] if key == -1 else [key], type=pa.int64())})
        handle.fetch_arrow_table.side_effect = fetch
        cases = list(tracker.lookup.KEYS)
        expected = {"gql_lookup": tracker.run.signature([[tracker.run.KEYS[0]]]),
                    "lookup_miss": tracker.run.signature([[]])}
        args = SimpleNamespace(route=tracker.lookup.QW_PARAM, provider="ladybug", block=1, runs=3)
        with patch.object(tracker.run, "cursor", return_value=nullcontext((parent, {}))) as open_session:
            worker = tracker.python_worker(args, {"cases": cases, "expected": expected, "session_lookups": True})
        open_session.assert_called_once()
        parent.execute.assert_called_once_with("SET SESSION qw_graph_dialect = 'cypher'")
        handle.adbc_prepare.assert_called_once_with(tracker.lookup.PARAM_QUERY)
        self.assertEqual(worker["setup"]["prepared_handles"], 1)
        self.assertEqual(handle.execute.call_args_list, [
            call(tracker.lookup.PARAM_QUERY, (tracker.lookup.KEYS[name],))
            for _, name in tracker.schedule(cases, 1, 3)])
        self.assertEqual(len(worker["samples"]), 8)

    def test_matched_ratio_uses_the_native_parameterized_handle(self):
        def worker(route, latency):
            return {"provider": "ladybug", "route": route, "samples": [
                {"case": "lookup_miss", "repetition": i, "wall_ms": value, "cpu_ms": value}
                for i, value in enumerate((100, latency))]}
        rows = tracker.summarize([worker("direct_cypher", 4), worker(tracker.lookup.DIRECT_PREPARED, 2),
                                  worker(tracker.lookup.DIRECT_PARAM, 1), worker(tracker.lookup.QW_PARAM, 8)])
        match = next(row for row in rows if row["route"] == tracker.lookup.QW_PARAM)
        self.assertEqual((match["n"], match["qw_over_direct"], match["qw_over_matched_direct"]), (1, 2, 8))
        self.assertEqual(match["matched_direct_route"], tracker.lookup.DIRECT_PARAM)

    def test_prepares_each_fixed_lookup_once_and_reuses_its_cursor(self):
        cases = {"lookup": [tracker.run.KEYS[0]], "lookup_miss": []}
        tables = {name: pa.table({"id": pa.array(values, type=pa.int64())})
                  for name, values in cases.items()}
        expected = {tracker.CASES[name][1]: tracker.run.signature([values])
                    for name, values in cases.items()}
        source = MagicMock()
        source.fetch_arrow_table.side_effect = lambda: tables[
            "lookup_miss" if " = -1" in source.execute.call_args.args[0] else "lookup"]
        prepared = {name: MagicMock() for name in cases}
        for name, cursor in prepared.items():
            cursor.fetch_arrow_table.return_value = tables[name]
        source.connection.cursor.side_effect = [nullcontext(cursor) for cursor in prepared.values()]
        args = SimpleNamespace(route="qw_prepared_cypher", provider="ladybug", block=0, runs=2)
        with patch.object(tracker.run, "cursor", return_value=nullcontext((source, {}))):
            worker = tracker.python_worker(args, {"cases": list(cases), "expected": expected})

        for name, cursor in prepared.items():
            graph_query = tracker.run.sql_literal(tracker.CASES[name][0])
            sql = f"SELECT * FROM qw_query('social', 'cypher', {graph_query}, schema := 'id BIGINT')"
            cursor.adbc_prepare.assert_called_once_with(sql)
            self.assertEqual(cursor.execute.call_args_list, [call(sql)] * 3)
        self.assertEqual(len(worker["samples"]), 6)
        self.assertGreaterEqual(worker["setup"]["prepare_ms"], 0)


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
        return {"block": block, "provider": provider, "route": route, "setup": {"open_ms": 4, "bootstrap_ms": 4}, "samples": [
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
