"""Verify and time standalone graph clients and QuackWeave hybrid queries on SF1."""
import argparse
from contextlib import ExitStack
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
from tempfile import NamedTemporaryFile
from time import perf_counter_ns, process_time_ns
from uuid import uuid4

import pyarrow as pa

import run
from planning.compare import OUTER, VIA_VIEW
from watchlist import SQL as VALUES_JOIN


# A case names one logical workload. Each direct baseline uses native Cypher.
STANDALONE = {
    "lookup": (run.POINT, "gql_lookup"),
    "lookup_miss": ("MATCH (p:Person) WHERE p.PersonId = -1 RETURN p.PersonId AS id", "lookup_miss"),
    "fanout": (run.FAN, "cypher_fanout"),
}
HYBRID = {
    "graph_table_where": (run.CASES["graph_table_where"][1], "graph_table_where"),
    "outer_where": (OUTER, "graph_table_where"),
    "view_where": (VIA_VIEW, "graph_table_where"),
    "values_watchlist": (VALUES_JOIN, "table_watchlist"),
    "table_watchlist": (run.CASES["table_watchlist"][1], "table_watchlist"),
    "full_scan_aggregate": (run.CASES["full_scan_aggregate"][1], "full_scan_aggregate"),
}
CASES = {**STANDALONE, **HYBRID}
ROUTES = {"direct_cypher": STANDALONE, "qw_gql": STANDALONE,
          "qw_cypher": STANDALONE, "qw_pgq": HYBRID}
READER = run.ROOT / "target/mvp2-relate/aarch64-apple-darwin/release/examples/relate_bench_read"
HISTORY = run.BUILD / "tracker"
PROTOCOL = 1


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
    with ExitStack() as stack:
        if a.route == "direct_cypher":
            import ladybug
            start = perf_counter_ns()
            db = stack.enter_context(ladybug.Database(a.fixture / run.ENGINES["ladybug"], read_only=True))
            conn = stack.enter_context(ladybug.Connection(db))
            setup = {"open_ms": run.milliseconds(start)}

            def fetch(statement):
                with conn.execute(statement) as result:
                    return result.get_as_arrow()
        else:
            cur, setup = stack.enter_context(run.cursor(a))
            dialect = "cypher" if a.route == "qw_cypher" else "gql"
            cur.execute("SET SESSION qw_graph_dialect = " + run.sql_literal(dialect))
            if "view_where" in request["cases"]:
                cur.execute("CREATE TEMP VIEW planning_pairs AS SELECT * FROM " + run.PAIRS)

            def fetch(statement):
                cur.execute(statement)
                return cur.fetch_arrow_table()

        samples = []
        for repetition, name in sequence:
            actual, timing = fetch_table(fetch, CASES[name][0])
            check_result(request["expected"], name, actual)
            samples.append({"repetition": repetition, "case": name, **timing})
        worker = {"setup": setup, "samples": samples,
                  "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20}
        if a.route == "qw_pgq":
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
    if (provider, route) == ("relate", "direct_cypher"):
        sequence = schedule(cases, block, a.runs)
        payload = "".join(json.dumps(CASES[name][0]) + "\n" for _, name in sequence)
        output = run_process([a.relate_reader, a.fixture / run.ENGINES[provider]], payload, a.timeout)
        setup, *observations, memory = map(json.loads, output.splitlines())
        samples = []
        for (repetition, name), observation in zip(sequence, observations, strict=True):
            check_result(expected, name, run.signature([observation.pop("ids")]))
            samples.append({"case": name, "repetition": repetition, **observation})
        measured = {"setup": setup, "samples": samples, **memory}
    else:
        command = [sys.executable, "-B", __file__, "_worker", "--provider", provider, "--route", route,
                   "--fixture", a.fixture, "--extension", a.extension, "--library", a.library,
                   "--runs", str(a.runs), "--block", str(block)]
        measured = json.loads(run_process(command, json.dumps({"expected": expected, "cases": cases}), a.timeout))
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
        if row["route"] in ("qw_gql", "qw_cypher"):
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


def benchmark(a):
    if sys.platform != "darwin" or a.runs < 1 or a.blocks < 2 or a.blocks % 2 or a.timeout <= 0:
        raise ValueError("Use macOS, positive runs/worker timeout and an even number of blocks >= 2")
    cases = [name for name in CASES if not a.case or name in a.case]
    providers = sorted(set(a.provider or run.ENGINES))
    started = datetime.now(timezone.utc)
    run_id = f"{started:%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
    path = a.out or HISTORY / (run_id + ".json")
    if path.exists():
        raise FileExistsError(f"Choose a new snapshot path: {path}")
    fixture = json.loads((a.fixture / "fixture.json").read_text())
    verify_fixture(a.fixture, fixture)
    oracle = run.oracle(a.fixture)
    if any(group[0] == -1 for group in oracle["watchlist_groups"]):
        raise ValueError("lookup_miss requires -1 to be absent")
    expected = {**oracle["expected"], "lookup_miss": run.signature([[]])}
    expected = {CASES[n][1]: expected[CASES[n][1]] for n in cases}
    routes = {k: [n for n in cases if n in group] for k, group in ROUTES.items()}
    binaries = {"extension": run.digest(a.extension), "duckdb_library": run.digest(a.library)}
    if "relate" in providers and routes["direct_cypher"]:
        binaries["relate_reader"] = run.digest(a.relate_reader)
    if "ladybug" in providers and routes["direct_cypher"] and version("ladybug") != "0.22.3":
        raise ValueError("The native Ladybug comparison requires ladybug==0.22.3")
    source_commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", "--end-of-options", a.source_revision + "^{commit}"],
        cwd=a.source_checkout, text=True).strip()
    report = {"protocol": PROTOCOL, "id": run_id, "started_utc": started.isoformat(),
              "tracker_sha256": run.digest(Path(__file__)),
              "workspace_head": source_commit,
              "platform": platform.platform(), "machine": platform.machine(),
              "host_id": sha256(platform.node().encode()).hexdigest()[:16],
              "versions": {"python": platform.python_version(), "duckdb": "2.0.1/8d78114e90",
                           "relate": "1.2.0", **{k: version(k) for k in ("ladybug", "pyarrow", "adbc-driver-manager")}},
              "binaries": binaries, "fixture": fixture, "edge_count": oracle["edges"], "duckdb_threads": 1,
              "blocks": a.blocks, "runs": a.runs, "expected": expected,
              "statements": {n: CASES[n][0] for n in cases}, "watchlist": run.KEYS, "workers": []}
    for block in range(a.blocks):
        order = 1 if block % 2 == 0 else -1
        for provider in providers[::order]:
            for route in list(routes)[::order]:
                if routes[route]:
                    try:
                        worker = measure_worker(a, provider, route, block, routes[route], expected)
                    except (ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                        raise RuntimeError(f"{provider} {route}, block {block + 1}: {error}") from error
                    report["workers"].append(worker)
                    print(f"Verified block {block + 1}/{a.blocks} {provider} {route}", flush=True)
    verify_fixture(a.fixture, fixture)
    report["summary"] = summarize(report["workers"])
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    publish(path, report)
    print(path)
    print("provider\troute\tcase\tn\tp50_ms\tp95_ms\tqw_over_direct")
    for row in report["summary"]:
        ratio = f"{row['qw_over_direct']:.2f}x" if "qw_over_direct" in row else "—"
        print(f"{row['provider']}\t{row['route']}\t{row['case']}\t{row['n']}\t"
              f"{row['p50_ms']:.3f}\t{row['p95_ms']:.3f}\t{ratio}")


def compare(old, new):
    before, after = [json.loads(p.read_text()) for p in (old, new)]
    for field in ("protocol", "fixture", "platform", "machine", "host_id", "duckdb_threads", "blocks", "runs", "watchlist"):
        if before[field] != after[field]:
            raise ValueError(f"Incompatible snapshots: {field} differs")
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
        cmd.add_argument("--fixture", type=Path, default=run.BUILD / "mod1")
        cmd.add_argument("--library", type=Path, default=run.LIB)
        cmd.add_argument("--extension", type=Path, default=run.EXT)
        cmd.add_argument("--runs", type=int, default=5)
    measure.add_argument("--provider", action="append", choices=run.ENGINES)
    measure.add_argument("--case", action="append", choices=CASES)
    measure.add_argument("--out", type=Path, help="New JSON file (default: timestamped history)")
    measure.add_argument("--relate-reader", type=Path, default=READER)
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
