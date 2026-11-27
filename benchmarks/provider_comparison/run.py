"""Time equivalent SQL on real Ladybug and Relate files through one QuackWeave release."""
import argparse
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
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

from adbc_driver_manager import dbapi
import numpy as np
import pyarrow.csv as csv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lsqb_sf1"))
from watchlist import KEYS, PATTERN, ROOT, digest, provider_rows, sql_literal

BUILD = ROOT / "build/perf/provider-comparison"
GRAPH_ALIAS = "social"
EXT = ROOT / "build/native/release/extension/quack_weave/quack_weave.duckdb_extension"
DUCKDB_LIBRARY = "libduckdb.so" if sys.platform == "linux" else "libduckdb.dylib"
LIB = ROOT / "build/benchmark-host/release/src" / DUCKDB_LIBRARY
if not LIB.is_file():
    LIB = ROOT / "build/deps/duckdb-v2.0.1" / DUCKDB_LIBRARY
POINT = f"MATCH (p:Person) WHERE p.PersonId = {KEYS[0]} RETURN p.PersonId AS id"
EQ = f"p.PersonId = {KEYS[0]}"
FAN = f"MATCH {PATTERN} WHERE {EQ} RETURN m.MessageId AS id"


def graph(columns, where=""):
    return f"GRAPH_TABLE ({GRAPH_ALIAS} MATCH {PATTERN} {where} COLUMNS ({columns})) AS g"


PAIRS = graph("p.PersonId AS author, m.MessageId AS mid")
CASES = {
    "gql_lookup": ("gql", POINT),
    "gql_fanout": ("gql", FAN),
    "cypher_fanout": ("cypher", FAN),
    "graph_table_where": ("gql", "SELECT mid FROM " + graph("m.MessageId AS mid", "WHERE " + EQ)),
    "table_watchlist": ("gql", "SELECT author, count(*), sum(mid % 1000003) FROM " + PAIRS
                       + " JOIN watch USING (author) GROUP BY author ORDER BY author"),
    "full_scan_aggregate": ("gql", "SELECT count(*), sum(mid % 1000003) FROM " + graph("m.MessageId AS mid")),
}
ENGINES = {"ladybug": "social.lbdb", "relate": "social.rl"}


def percentiles(values):
    values = sorted(values)
    return {"n": len(values), "p50_ms": median(values), "p95_ms": values[math.ceil(.95 * len(values)) - 1]}


def verify_fixture(folder, manifest):
    for filename in ("edges.csv", *ENGINES.values()):
        if digest(folder / filename) != manifest["files"][filename]["sha256"]:
            raise ValueError(f"Fixture checksum mismatch: {filename}")


def publish(path, report):
    # A failed run or simultaneous publisher cannot replace a verified baseline.
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", dir=path.parent, encoding="utf-8") as tmp:
        json.dump(report, tmp, indent=2, allow_nan=False)
        tmp.write("\n")
        tmp.flush()
        os.link(tmp.name, path)


def signature(columns):
    # Sort the whole row, retain duplicates, encode canonical little-endian int64 values.
    data = np.column_stack(columns).astype("<i8", copy=False)
    order = np.lexsort(data.T[::-1])
    return [len(data), hashlib.sha256(data[order].tobytes()).hexdigest()]


def oracle(folder):
    pairs = csv.read_csv(folder / "edges.csv")
    authors, mids = [c.to_numpy() for c in pairs.columns]
    fan = mids[authors == KEYS[0]]
    if not len(fan):
        raise ValueError("Point and fan-out key absent from the fixture")
    groups = []
    for key in KEYS:
        selected = mids[authors == key]
        if len(selected):
            groups.append((key, len(selected), int((selected % 1000003).sum())))
    scan = [len(mids), int((mids % 1000003).sum())]
    boundaries = np.unique(authors[::300000]).tolist() + [int(authors[-1]) + 1]
    partitions = []
    for low, high in zip(boundaries, boundaries[1:]):
        mask = (authors >= low) & (authors < high)
        partitions.append([low, high, signature([authors[mask], mids[mask]])])
    return {"edges": len(mids), "people": len(np.unique(authors)), "messages": len(mids),
            "fanout": len(fan), "watchlist_groups": groups, "scan": scan, "partitions": partitions,
            "expected": {"all_pairs": signature([authors, mids]), "gql_lookup": signature([[KEYS[0]]]),
                         "lookup_miss": signature([np.unique(authors[authors == -1])]),
                         **{k: signature([fan]) for k in ["gql_fanout", "cypher_fanout", "graph_table_where"]},
                         "table_watchlist": signature(list(zip(*groups))),
                         "full_scan_aggregate": signature([[v] for v in scan])}}


def milliseconds(start):
    return (perf_counter_ns() - start) / 1e6


@contextmanager
def duckdb_cursor(a):
    start = perf_counter_ns()
    with dbapi.connect(driver=str(a.library.resolve()), entrypoint="duckdb_adbc_init", autocommit=True,
                       db_kwargs={"allow_unsigned_extensions": "true"}) as db, db.cursor() as cur:
        open_ms = milliseconds(start)
        cur.execute("SELECT library_version, source_id FROM pragma_version()")
        if cur.fetchone() != ("v2.0.1", "8d78114e90"):
            raise ValueError("Unexpected DuckDB version")
        start = perf_counter_ns()
        cur.execute("SET threads = 1")
        threads_ms = milliseconds(start)
        yield cur, {"open_ms": open_ms, "threads_ms": threads_ms}


@contextmanager
def cursor(a, *, prepare_watchlist=True):
    graph_path = a.fixture / ENGINES[a.provider]
    config = json.dumps({"alias": GRAPH_ALIAS, "path": str(graph_path.resolve())})
    with duckdb_cursor(a) as (cur, setup):
        start = perf_counter_ns()
        cur.execute("LOAD " + sql_literal(a.extension.resolve()))
        load_ms = milliseconds(start)
        start = perf_counter_ns()
        cur.execute(f"SET GLOBAL qw_{a.provider}_config = " + sql_literal(config))
        register_ms = milliseconds(start)
        start = perf_counter_ns()
        cur.execute(f"SESSION SET GRAPH {GRAPH_ALIAS}")
        select_graph_ms = milliseconds(start)
        if prepare_watchlist:
            cur.execute("CREATE TEMP TABLE watch(author BIGINT)")
            cur.execute("INSERT INTO watch VALUES " + ",".join(f"({k})" for k in KEYS))
        setup.update(load_ms=load_ms, register_ms=register_ms, select_graph_ms=select_graph_ms)
        yield cur, {**setup, "bootstrap_ms": sum(setup.values())}


def fetch(cur, stmt):
    start_cpu = process_time_ns()
    start = perf_counter_ns()
    cur.execute(stmt)
    table = cur.fetch_arrow_table()
    wall = milliseconds(start)
    cpu = (process_time_ns() - start_cpu) / 1e6
    return signature([c.to_numpy(zero_copy_only=False) for c in table.columns]), {"wall_ms": wall, "cpu_ms": cpu}


def worker(a):
    request = json.load(sys.stdin)
    expected = request["expected"]
    with cursor(a) as (cur, setup):
        def checked(name, stmt):
            answer, sample = fetch(cur, stmt)
            if answer != expected[name]:
                raise ValueError(f"{a.provider} {name}: {answer} != {expected[name]}")
            return sample
        if a.verify:
            # In a separate process: full pair materialization does not inflate timed workers' RSS.
            scans, failures = {}, {}
            verification = {"mode": "one scan"}
            try:
                checked("all_pairs", "SELECT author, mid FROM " + PAIRS)
            except dbapi.Error as error:
                # Same multiset, partitioned by a vertex key *inside* the provider query.
                # First count every edge to rule out extra rows outside the partition bounds.
                native = f"MATCH {PATTERN} RETURN count(*) AS n"
                cur.execute(f"FROM qw_query('social','cypher',{sql_literal(native)},schema := 'n BIGINT')")
                if cur.fetchone() != (expected["all_pairs"][0],):
                    raise ValueError("Unexpected full edge count")
                for low, high, checksum in request["partitions"]:
                    native = (f"MATCH (p:Person) WHERE p.PersonId >= {low} AND p.PersonId < {high} "
                              "WITH p MATCH (p)<-[:Message_hasCreator_Person]-(m:Message) "
                              "RETURN p.PersonId AS author, m.MessageId AS mid")
                    sql = f"FROM qw_query('social','cypher',{sql_literal(native)},schema := 'author BIGINT, mid BIGINT')"
                    if fetch(cur, sql)[0] != checksum:
                        raise ValueError(f"Edge mismatch in [{low}, {high})")
                verification = {"mode": "disjoint author ranges", "partitions": len(request["partitions"]),
                                "single_scan_error": str(error)}
            for name in ("graph_table_where", "table_watchlist", "full_scan_aggregate"):
                try:
                    cur.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + CASES[name][1])
                    plan = cur.fetchone()[1]
                except dbapi.Error as error:
                    # Confirm the public query itself fails before excluding it from timing.
                    try:
                        checked(name, CASES[name][1])
                    except dbapi.Error as query_error:
                        failures[name] = str(query_error)
                    scans[name] = None
                    continue
                counts = list(provider_rows(json.loads(plan)["operator"]))
                if len(counts) != 1:
                    raise ValueError(f"Expected exactly one graph scan for {name}, found {counts}")
                scans[name] = counts[0]
            return {"all_pairs": expected["all_pairs"], "verification": verification,
                    "provider_rows": scans, "failed_queries": failures}
        first = checked("gql_lookup", POINT)
        measurements = []
        for iteration in range(a.runs + 1):
            names = [name for name in request.get("cases", CASES) if name not in request.get("failed", {})]
            random.Random(7411 + 101 * a.block + iteration).shuffle(names)
            for name in names:
                dialect, stmt = CASES[name]
                cur.execute("SET SESSION qw_graph_dialect = " + sql_literal(dialect))
                sample = checked(name, stmt)
                if iteration:
                    measurements.append({"case": name, "iteration": iteration, **sample})
        return {"block": a.block, "provider": a.provider, "setup": setup, "first_lookup": first,
                "samples": measurements,
                "worker_peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20}


def summarize(workers):
    by_case = defaultdict(list)
    for item in workers:
        for sample in item["samples"]:
            by_case[(item["provider"], sample["case"])].append(sample)
    rows = []
    for case in CASES:
        row = {"case": case}
        for engine in ENGINES:
            samples = by_case[engine, case]
            if not samples:
                row[engine] = {"n": 0, "p50_ms": None, "p95_ms": None, "median_cpu_ms": None}
                continue
            row[engine] = {**percentiles(s["wall_ms"] for s in samples),
                           "median_cpu_ms": median(s["cpu_ms"] for s in samples)}
        row["relate_over_ladybug"] = (row["relate"]["p50_ms"] / row["ladybug"]["p50_ms"]
                                      if row["relate"]["n"] and row["ladybug"]["n"] else None)
        rows.append(row)
    return rows


def benchmark(a):
    if platform.system() != "Darwin" or a.runs < 1 or a.blocks < 2 or a.blocks % 2:
        raise ValueError("Expected macOS, positive repeats, and an even number of blocks >= 2")
    info = json.loads((a.fixture / "fixture.json").read_text())
    def check_files():
        for name, data in info["files"].items():
            if digest(a.fixture / name) != data["sha256"]:
                raise ValueError(f"Fixture changed: {name}")
    check_files()
    reference = oracle(a.fixture)
    result = {"start_utc": datetime.now(timezone.utc).isoformat(), "fixture": info, "oracle": reference,
              "workspace_head": subprocess.check_output(["git","rev-parse","HEAD"], cwd=ROOT, text=True).strip(),
              "platform": platform.platform(), "python": platform.python_version(), "duckdb": "v2.0.1 8d78114e90",
              "versions": {k: version(k) for k in ["pyarrow", "adbc-driver-manager", "ladybug"]},
              "relate": "1.2.0", "duckdb_threads": 1, "extension_sha256": digest(a.extension),
              "library_sha256": digest(a.library), "watchlist": KEYS, "cases": CASES,
              "runs": a.runs, "blocks": a.blocks, "parity": {}, "workers": []}
    def launch(engine, block, verify=False):
        cmd = [sys.executable, "-B", __file__, "--fixture", a.fixture, "--extension", a.extension,
               "--library", a.library, "--provider", engine, "--block", str(block), "--runs", str(a.runs)]
        if verify:
            cmd.append("--verify")
        request = {"expected": reference["expected"], "partitions": reference["partitions"],
                   "failed": result["parity"].get(engine, {}).get("failed_queries", {})}
        sub = subprocess.run(cmd, input=json.dumps(request), text=True, capture_output=True)
        if sub.returncode:
            raise RuntimeError(f"{engine} worker exited {sub.returncode}\n{sub.stderr}")
        return json.loads(sub.stdout)
    for engine in ENGINES:
        result["parity"][engine] = launch(engine, 0, verify=True)
    for block in range(a.blocks):
        for engine in list(ENGINES)[::(-1 if block % 2 else 1)]:
            result["workers"].append(launch(engine, block))
            print(f"{a.fixture.name} block {block+1}/{a.blocks} {engine} verified", flush=True)
    check_files()
    result["summary"] = summarize(result["workers"])
    result["finish_utc"] = datetime.now(timezone.utc).isoformat()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fixture", type=Path, required=True)
    p.add_argument("--library", type=Path, default=LIB)
    p.add_argument("--extension", type=Path, default=EXT)
    p.add_argument("--runs", type=int, default=4)
    p.add_argument("--blocks", type=int, default=4)
    p.add_argument("--out", type=Path)
    p.add_argument("--provider", choices=ENGINES, help=argparse.SUPPRESS)
    p.add_argument("--block", type=int, default=0, help=argparse.SUPPRESS)
    p.add_argument("--verify", action="store_true", help=argparse.SUPPRESS)
    a = p.parse_args()
    if a.provider:
        print(json.dumps(worker(a)))
    else:
        if not a.out:
            p.error("--out is required")
        benchmark(a)
