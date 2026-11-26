"""Verify and time standalone graph clients and QuackWeave hybrid queries on SF1."""
import argparse
from contextlib import ExitStack
from copy import copy
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import platform
import random
import resource
from statistics import median
import subprocess
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory
from time import perf_counter_ns, process_time_ns
from uuid import uuid4

import pyarrow as pa

import micro_workloads as micro
import run
from planning.compare import OUTER, VIA_VIEW
from watchlist import SQL as VALUES_JOIN


# A case names one logical workload. Each direct baseline uses native Cypher.
MICRO_CASES = {name: (sql, name) for name, sql in micro.statements(run.PAIRS).items()}
MICRO_HOST_ROUTE = "qw_pgq_host"
STANDALONE = {
    "lookup": (run.POINT, "gql_lookup"),
    "lookup_miss": ("MATCH (p:Person) WHERE p.PersonId = -1 RETURN p.PersonId AS id", "lookup_miss"),
    "fanout": (run.FAN, "cypher_fanout"),
}
HYBRID = {
    **MICRO_CASES,
    "graph_table_where": (run.CASES["graph_table_where"][1], "graph_table_where"),
    "outer_where": (OUTER, "graph_table_where"),
    "view_where": (VIA_VIEW, "graph_table_where"),
    "values_watchlist": (VALUES_JOIN, "table_watchlist"),
    "table_watchlist": (run.CASES["table_watchlist"][1], "table_watchlist"),
    "full_scan_aggregate": (run.CASES["full_scan_aggregate"][1], "full_scan_aggregate"),
}
CASES = {**STANDALONE, **HYBRID}
PREPARED_ROUTE = "qw_prepared_cypher"
ROUTES = {"direct_cypher": STANDALONE, "qw_gql": STANDALONE,
          "qw_cypher": STANDALONE, PREPARED_ROUTE: STANDALONE, "qw_pgq": HYBRID,
          MICRO_HOST_ROUTE: MICRO_CASES}
HISTORY = run.BUILD / "tracker"
PROTOCOL = 2


def schedule(cases, block, runs):
    series = []
    for repetition in range(runs + 1):
        names = list(cases)
        random.Random(7411 + 101 * block + repetition).shuffle(names)
        series.extend((repetition, name) for name in names)
    return series


def check_result(expected, name, actual):
    if actual != expected[CASES[name][1]]:
        raise ValueError(f"{name}: incorrect result; expected {expected[CASES[name][1]]}, got {actual}")


def prepared_sql(name):
    alias = run.sql_literal(run.GRAPH_ALIAS)
    statement = run.sql_literal(STANDALONE[name][0])
    return f"SELECT * FROM qw_query({alias}, 'cypher', {statement}, schema := 'id BIGINT')"


def fetch_table(fetch, statement):
    cpu = process_time_ns()
    start = perf_counter_ns()
    table = fetch(statement)
    timing = {"wall_ms": run.milliseconds(start), "cpu_ms": (process_time_ns() - cpu) / 1e6}
    for column in table.columns:
        if column.null_count or not (pa.types.is_integer(column.type) or
                                     (pa.types.is_decimal(column.type) and column.type.scale == 0)):
            raise ValueError(f"Expected non-null integers from this SF1 workload, got {table.schema}")
    return run.signature([c.to_numpy(zero_copy_only=False) for c in table.columns]), timing


def python_worker(a, request):
    sequence = schedule(request["cases"], a.block, a.runs)
    statements = {name: CASES[name][0] for name in request["cases"]}
    with ExitStack() as stack:
        if a.route == "direct_cypher" and a.provider == "relate":
            from relate import Database
            start = perf_counter_ns()
            db = Database(str(a.fixture / run.ENGINES["relate"]), read_only=True)
            stack.callback(db.close)
            setup = {"open_ms": run.milliseconds(start)}

            def fetch(statement):
                table = pa.ipc.open_stream(db.execute_arrow(statement)).read_all()
                if table.column_names != ["id"]:
                    raise ValueError(f"Unexpected direct RelateDB schema: {table.schema}")
                # The wheel reports string for an empty, untyped Cypher result.
                return table if table.num_rows else table.cast(pa.schema([("id", pa.int64())]))
        elif a.route == "direct_cypher":
            import ladybug
            start = perf_counter_ns()
            db = stack.enter_context(ladybug.Database(a.fixture / run.ENGINES["ladybug"], read_only=True))
            conn = stack.enter_context(ladybug.Connection(db))
            setup = {"open_ms": run.milliseconds(start)}

            def fetch(statement):
                with conn.execute(statement) as result:
                    return result.get_as_arrow()
        elif a.route == PREPARED_ROUTE:
            parent, setup = stack.enter_context(run.cursor(a))
            statements = {name: prepared_sql(name) for name in request["cases"]}
            cursors = {}
            start = perf_counter_ns()
            for statement in statements.values():
                cursor = stack.enter_context(parent.connection.cursor())
                cursor.adbc_prepare(statement)
                cursors[statement] = cursor
            setup["prepare_ms"] = run.milliseconds(start)

            def fetch(statement):
                cursor = cursors[statement]
                cursor.execute(statement)
                return cursor.fetch_arrow_table()
        else:
            cur, setup = stack.enter_context(run.cursor(a))
            dialect = "cypher" if a.route == "qw_cypher" else "gql"
            cur.execute("SET SESSION qw_graph_dialect = " + run.sql_literal(dialect))
            if "view_where" in request["cases"]:
                cur.execute("CREATE TEMP VIEW planning_pairs AS SELECT * FROM " + run.PAIRS)
            if "micro_relations" in request:
                micro.setup(cur, request["micro_relations"], prefilter=a.route != MICRO_HOST_ROUTE)

            def fetch(statement):
                cur.execute(statement)
                return cur.fetch_arrow_table()

        samples = []
        for repetition, name in sequence:
            actual, timing = fetch_table(fetch, statements[name])
            check_result(request["expected"], name, actual)
            samples.append({"repetition": repetition, "case": name, **timing})
        worker = {"setup": setup, "samples": samples,
                  "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (2**20 if sys.platform == "darwin" else 1024)}
        if a.route in ("qw_pgq", MICRO_HOST_ROUTE):
            crossings = {}
            for name in request["cases"]:
                cur.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + CASES[name][0])
                (crossings[name],) = run.provider_rows(json.loads(cur.fetchone()[1])["operator"])
            worker["graph_scan_rows"] = crossings
        return worker


def run_process(command, payload, timeout):
    result = subprocess.run(command, input=payload, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"Benchmark worker exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout


def measure_worker(a, provider, route, block, cases, expected):
    command = [sys.executable, "-B", __file__, "_worker", "--provider", provider, "--route", route,
               "--fixture", a.fixture, "--extension", a.extension, "--library", a.library,
               "--runs", str(a.runs), "--block", str(block)]
    payload = {"expected": expected, "cases": cases}
    if getattr(a, "micro", False):
        payload["micro_relations"] = a.micro_relations
    measured = json.loads(run_process(command, json.dumps(payload), a.timeout))
    return {"block": block, "provider": provider, "route": route, **measured}


def summarize(workers):
    series = {}
    for worker in workers:
        for sample in worker["samples"]:
            key = (worker["provider"], worker["route"], sample["case"])
            if sample["repetition"]:
                series.setdefault(key, []).append(sample)
    rows = []
    for (provider, route, case), samples in sorted(series.items()):
        wall = sorted(s["wall_ms"] for s in samples)
        rows.append({"provider": provider, "scope": "hybrid" if case in HYBRID else "standalone",
                     "route": route, "case": case, "n": len(samples), "p50_ms": median(wall),
                     "p95_ms": wall[math.ceil(.95 * len(wall)) - 1],
                     "cpu_p50_ms": median(s["cpu_ms"] for s in samples)})
    native = {(r["provider"], r["case"]): r["p50_ms"] for r in rows if r["route"] == "direct_cypher"}
    for row in rows:
        if row["route"] in ("qw_gql", "qw_cypher", PREPARED_ROUTE):
            row["qw_over_direct"] = row["p50_ms"] / native[row["provider"], row["case"]]
    return rows


def verify_fixture(folder, manifest):
    for filename in ("edges.csv", *run.ENGINES.values()):
        if run.digest(folder / filename) != manifest["files"][filename]["sha256"]:
            raise ValueError(f"Fixture checksum mismatch: {filename}")


def publish(path, report):
    # A failed run or simultaneous publisher cannot replace a verified baseline.
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", dir=path.parent, encoding="utf-8") as tmp:
        json.dump(report, tmp, indent=2, allow_nan=False)
        tmp.write("\n")
        tmp.flush()
        os.link(tmp.name, path)


def release_metadata(a, common, binaries):
    source_commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", "--end-of-options", a.source_revision + "^{commit}"],
        cwd=a.source_checkout, text=True).strip()
    return {**common, "workspace_head": source_commit, "binaries": {**binaries, "extension": run.digest(a.extension)}}


def verify_micro(a, report, providers, expected_rows):
    """Require SQLLogic query and snapshot checks before publishing a CM-LDBC record."""
    sys.path.insert(0, str(run.ROOT / "test" / "stabilization"))
    try:
        from run_sqllogictest import PIN_PROBE_SQL, run_cases
    finally:
        sys.path.pop(0)

    test_dir = Path(__file__).resolve().parent / "tracker"
    results_test = test_dir / "micro_results.test"
    snapshot_test = test_dir / "micro_snapshot.test"
    with TemporaryDirectory(prefix="qw-micro-") as directory:
        scratch = Path(directory).resolve()
        snapshot = scratch / "snapshot.json"
        snapshot.write_text(json.dumps(report, allow_nan=False), encoding="utf-8")
        run_cases(a.duckdb_unittest, scratch, {}, stdin=PIN_PROBE_SQL)
        for provider in providers:
            variables = micro.sqllogic_variables(
                a.extension, a.fixture / run.ENGINES[provider], provider, run.GRAPH_ALIAS,
                a.micro_relations, expected_rows, report["statements"],
            )
            run_cases(a.duckdb_unittest, scratch, variables, [results_test])
        run_cases(a.duckdb_unittest, scratch, {"QW_TRACKER_SNAPSHOT": snapshot}, [snapshot_test])
    return {"providers": providers, "checks": {test.name: run.digest(test) for test in (results_test, snapshot_test)}}


def benchmark(a):
    supported_host = (platform.system(), platform.machine()) in {("Darwin", "arm64"), ("Linux", "aarch64")}
    if not supported_host or a.runs < 1 or a.blocks < 2 or a.blocks % 2 or a.timeout <= 0:
        raise ValueError("Use native ARM64 Linux or macOS, positive runs/worker timeout and an even number of blocks >= 2")
    is_micro = getattr(a, "micro", False)
    if a.fixture is None:
        a.fixture = run.BUILD / ("mod32" if is_micro else "mod1")
    suite = MICRO_CASES if is_micro else [name for name in CASES if name not in MICRO_CASES]
    if set(a.case or []) - set(suite):
        raise ValueError("Select CM-LDBC cases with --micro and other cases without it")
    cases = [name for name in suite if not a.case or name in a.case]
    providers = sorted(set(a.provider or run.ENGINES))
    if is_micro:
        if a.include_prepared:
            raise ValueError("CM-LDBC measures hybrid SQL without standalone prepared lookups")
        if not a.describe:
            a.duckdb_unittest = a.duckdb_unittest.resolve(strict=True)
    pairing = (a.baseline_extension, a.baseline_revision, a.baseline_out)
    supplied = [arg is not None for arg in pairing]
    if any(supplied) and not all(supplied):
        raise ValueError("Supply baseline extension, revision and output together")
    if a.describe and (a.out or any(supplied)):
        raise ValueError("Use --describe alone to write the candidate workload description")
    fixture = json.loads((a.fixture / "fixture.json").read_text())
    verify_fixture(a.fixture, fixture)
    if is_micro:
        csv_path = a.fixture / "edges.csv"
        a.micro_relations, edge_count = micro.fixture_inputs(csv_path)
        rows = micro.expected_rows(micro.edge_rows(csv_path), a.micro_relations)
        expected = {name: run.signature(list(zip(*rows[name]))) for name in cases}
    else:
        oracle = run.oracle(a.fixture)
        if any(group[0] == -1 for group in oracle["watchlist_groups"]):
            raise ValueError("lookup_miss requires -1 to be absent")
        expected = {**oracle["expected"], "lookup_miss": run.signature([[]])}
        expected = {CASES[n][1]: expected[CASES[n][1]] for n in cases}
        edge_count = oracle["edges"]
    routes = {k: [n for n in cases if n in group] for k, group in ROUTES.items()
              if k != PREPARED_ROUTE or a.include_prepared}
    binaries = {"duckdb_library": run.digest(a.library)}
    if "relate" in providers and routes["direct_cypher"]:
        import relate._native
        if version("relate-db") != "1.2.0":
            raise ValueError("The native RelateDB comparison requires relate-db==1.2.0")
        binaries["relate_driver"] = run.digest(Path(relate._native.__file__))
    if "ladybug" in providers and routes["direct_cypher"]:
        import ladybug._lbug
        if version("ladybug") != "0.22.3":
            raise ValueError("The native Ladybug comparison requires ladybug==0.22.3")
        binaries["ladybug_driver"] = run.digest(Path(ladybug._lbug.__file__))
    common = {"protocol": PROTOCOL,
              "tracker_sha256": run.digest(Path(__file__)),
              "platform": platform.platform(), "machine": platform.machine(),
              "host_id": sha256(platform.node().encode()).hexdigest()[:16],
              "versions": {"python": platform.python_version(), "duckdb": "2.0.1/8d78114e90",
                           "relate": "1.2.0", **{k: version(k) for k in ("ladybug", "pyarrow", "adbc-driver-manager", "numpy")}},
              "fixture": fixture, "edge_count": edge_count, "duckdb_threads": 1,
              "blocks": a.blocks, "runs": a.runs, "expected": expected,
              "statements": {n: CASES[n][0] for n in cases}, "watchlist": None if is_micro else run.KEYS}
    if is_micro:
        common["micro"] = {"source_revision": micro.REVISION, "host_threshold": micro.HOST_THRESHOLD,
                           "relations": a.micro_relations, "providers": providers}
        common["micro_workloads_sha256"] = run.digest(Path(micro.__file__))
    if routes.get(PREPARED_ROUTE):
        common["prepared_statements"] = {name: prepared_sql(name) for name in routes[PREPARED_ROUTE]}
    if a.describe:
        description = release_metadata(a, common, binaries)
        description["summary"] = [{"provider": provider, "route": route, "case": name}
                                  for provider in providers for route in routes for name in routes[route]]
        publish(a.describe, description)
        return
    releases = [a]
    if all(supplied):
        baseline = copy(a)
        baseline.extension, baseline.source_revision, baseline.out = pairing
        releases.insert(0, baseline)
        common["pair_id"] = uuid4().hex
    subjects = []
    for release in releases:
        started = datetime.now(timezone.utc)
        run_id = f"{started:%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
        path = release.out or HISTORY / (run_id + ".json")
        if path.exists():
            raise FileExistsError(f"Choose a new snapshot path: {path}")
        report = release_metadata(release, common, binaries)
        report.update(id=run_id, started_utc=started.isoformat(), workers=[])
        subjects.append((release, path, report))
    if len({path.resolve() for _, path, _ in subjects}) != len(subjects):
        raise ValueError("Use distinct snapshot outputs for baseline and candidate")
    for block in range(a.blocks):
        order = 1 if block % 2 == 0 else -1
        for position, (release, _, report) in enumerate(subjects[::order]):
            for provider in providers[::order]:
                for route in list(routes)[::order]:
                    if not routes[route]:
                        continue
                    try:
                        worker = measure_worker(release, provider, route, block, routes[route], expected)
                    except (ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                        raise RuntimeError(f"{report['workspace_head']} {provider} {route}, block {block + 1}: {error}") from error
                    if "pair_id" in report:
                        worker["pair_position"] = position
                    report["workers"].append(worker)
                    print(f"Verified block {block + 1}/{a.blocks} {report['workspace_head'][:12]} {provider} {route}", flush=True)
    verify_fixture(a.fixture, fixture)
    for release, _, report in subjects:
        report["summary"] = summarize(report["workers"])
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        if is_micro:
            report["micro_sqllogic"] = verify_micro(release, report, providers, rows)
    if is_micro:
        verify_fixture(a.fixture, fixture)
    with ExitStack() as rollback:
        for _, path, report in subjects:
            publish(path, report)
            rollback.callback(path.unlink)
        rollback.pop_all()
    for _, path, report in subjects:
        print_summary(path, report)


def print_summary(path, report):
    print(path)
    print("provider\troute\tcase\tn\tp50_ms\tp95_ms\tqw_over_direct")
    for row in report["summary"]:
        ratio = f"{row['qw_over_direct']:.2f}x" if "qw_over_direct" in row else "—"
        print(f"{row['provider']}\t{row['route']}\t{row['case']}\t{row['n']}\t"
              f"{row['p50_ms']:.3f}\t{row['p95_ms']:.3f}\t{ratio}")

    if "micro" in report:
        crossings = {}
        for worker in report["workers"]:
            for case, rows in worker["graph_scan_rows"].items():
                crossings.setdefault((worker["provider"], worker["route"], case), set()).add(rows)
        print("CM-LDBC provider rows delivered to DuckDB")
        print("provider\troute\tcase\trows_min\trows_max")
        for key, rows in sorted(crossings.items()):
            print(*key, min(rows), max(rows), sep="\t")


def compare(old, new):
    before, after = [json.loads(p.read_text()) for p in (old, new)]
    for field in ("protocol", "fixture", "platform", "machine", "host_id", "duckdb_threads", "blocks", "runs", "watchlist", "versions"):
        if before[field] != after[field]:
            raise ValueError(f"Incompatible snapshots: {field} differs")
    if before.get("prepared_statements") != after.get("prepared_statements"):
        raise ValueError("Incompatible snapshots: prepared statements differ")
    if before.get("micro") != after.get("micro"):
        raise ValueError("Incompatible snapshots: CM-LDBC inputs differ")
    if before["id"] == after["id"]:
        raise ValueError("Select two distinct benchmark runs")
    def by_key(report):
        return {(r["provider"], r["route"], r["case"]): r for r in report["summary"]}
    baseline = by_key(before)
    candidate = by_key(after)
    if baseline.keys() != candidate.keys() or before["statements"] != after["statements"] or before["expected"] != after["expected"]:
        raise ValueError("Incompatible snapshots: workload matrix, statement or oracle differs")
    print(f"{before['id']} -> {after['id']}")
    print("provider\troute\tcase\told_p50_ms\tnew_p50_ms\tp50_change_pct\told_p95_ms\tnew_p95_ms")
    for key, current in candidate.items():
        past = baseline[key]
        delta = 100 * (current["p50_ms"] / past["p50_ms"] - 1)
        print(*key, f"{past['p50_ms']:.3f}", f"{current['p50_ms']:.3f}", f"{delta:+.1f}",
              f"{past['p95_ms']:.3f}", f"{current['p95_ms']:.3f}", sep="\t")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    cmds = parser.add_subparsers(dest="command", required=True)
    cmds.add_parser("list", help="Show each case and eligible execution routes")
    diff = cmds.add_parser("compare", help="Compare two verified snapshots")
    diff.add_argument("old", type=Path)
    diff.add_argument("new", type=Path)
    measure = cmds.add_parser("run", help="Verify results, measure timings, and save an immutable snapshot")
    worker = cmds.add_parser("_worker", help=argparse.SUPPRESS)
    for cmd in (measure, worker):
        cmd.add_argument("--fixture", type=Path)
        cmd.add_argument("--library", type=Path, default=Path(os.environ.get("DUCKDB_LIB", run.LIB)))
        cmd.add_argument("--extension", type=Path, default=run.EXT)
        cmd.add_argument("--runs", type=int, default=5)
    measure.add_argument("--provider", action="append", choices=run.ENGINES)
    measure.add_argument("--case", action="append", choices=CASES)
    measure.add_argument("--micro", action="store_true", help="Measure the CM-LDBC hybrid workload suite")
    measure.add_argument("--duckdb-unittest", type=Path,
                         default=Path(os.environ.get("DUCKDB_UNITTEST", run.ROOT / "build/benchmark-host/unittest")),
                         help="Pinned SQLLogic runner for the CM-LDBC workload and snapshot gates")
    measure.add_argument("--include-prepared", action="store_true",
                         help="Also time reused explicit-schema qw_query Cypher statements")
    measure.add_argument("--out", type=Path, help="New JSON file (default: timestamped history)")
    measure.add_argument("--describe", type=Path, help="Write candidate workload metadata before measuring")
    measure.add_argument("--baseline-extension", type=Path, help="Verified baseline extension to alternate with the candidate")
    measure.add_argument("--baseline-revision", help="Git revision of the baseline artifact")
    measure.add_argument("--baseline-out", type=Path, help="New JSON file for the paired baseline measurements")
    measure.add_argument("--source-revision", default="HEAD", help="Git revision of the verified release artifact")
    measure.add_argument("--source-checkout", type=Path, default=run.ROOT,
                         help="Git checkout used to build the measured extension")
    measure.add_argument("--blocks", type=int, default=4)
    measure.add_argument("--timeout", type=int, default=300, help="Maximum seconds per worker process")
    worker.add_argument("--provider", required=True, choices=run.ENGINES)
    worker.add_argument("--route", required=True, choices=ROUTES)
    worker.add_argument("--block", required=True, type=int)
    a = parser.parse_args()
    if a.command == "list":
        for name in CASES:
            print(name, *(route for route, group in ROUTES.items() if name in group), sep="\t")
    elif a.command == "run":
        benchmark(a)
    elif a.command == "compare":
        compare(a.old, a.new)
    else:
        print(json.dumps(python_worker(a, json.load(sys.stdin))))


if __name__ == "__main__":
    main()
