"""Benchmark the public graph and hybrid usage patterns on the pinned LSQB SF1 release.

Run build/usage-client-venv/bin/python -B benchmarks/lsqb_sf1/usage_regression.py
from the repository root. Each engine/block runs in its own sequential process.
"""

import argparse
from collections import defaultdict
from contextlib import ExitStack
from datetime import datetime, timezone
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
from time import perf_counter_ns, process_time_ns

from watchlist import (
    GRAPH_SHA,
    KEYS,
    NATIVE,
    PATTERN,
    ROOT,
    SQL,
    VALUES,
    digest,
    provider_rows,
    provision,
    sql_literal,
)

HERE = Path(__file__).resolve().parent
PERF = ROOT / "build/perf/lsqb-sf1"
GRAPH = PERF / "sf1.lbdb"
LIB = ROOT / "build/deps/duckdb-v2.0.1/libduckdb.dylib"
PACKAGES = {
    "baseline": PERF / "baseline-ecfcd8e/quack_weave.duckdb_extension",
    "current": ROOT / "build/native/release/extension/quack_weave/quack_weave.duckdb_extension",
}
PINS = {
    "baseline": ("ecfcd8e", "1385701536ca193c1f423d2c6c60c68b60ac1463d9941a9fbf7e310b9ed97c14"),
    "current": ("a2098d7", "7f8596688d59e129c18ec797da6e0522796ec64c6c7bb593360bc384c4e0f096"),
}
EQ = f"p.PersonId = {KEYS[0]}"
INS = "p.PersonId IN (" + ", ".join(map(str, KEYS)) + ")"
POINT = f"MATCH (p:Person) WHERE {EQ} RETURN p.PersonId AS id"
FAN = f"MATCH {PATTERN} WHERE {EQ} RETURN m.MessageId AS id"
AGG = "count(*) AS n, sum(mid % 1000003) AS fingerprint"
NATIVE_AGG = AGG.replace("mid", "m.MessageId")


def edges(where=""):
    where = " WHERE " + where if where else ""
    return (
        f"GRAPH_TABLE (social MATCH {PATTERN}{where} COLUMNS (p.PersonId AS author, m.MessageId AS mid)) AS g"
    )


def grouped(source):
    return f"SELECT g.author, {AGG} FROM {source} GROUP BY g.author ORDER BY g.author"


ORACLES = {
    "point": POINT,
    "fanout": FAN,
    "top": FAN + " ORDER BY id LIMIT 10",
    "fan_agg": f"MATCH {PATTERN} WHERE {EQ} RETURN {NATIVE_AGG}",
    "scan": f"MATCH {PATTERN} RETURN {NATIVE_AGG}",
    "groups": NATIVE,
    "exists": f"MATCH {PATTERN} WHERE p.PersonId IN {KEYS} RETURN DISTINCT p.PersonId AS author ORDER BY author",
    # Every message has exactly one creator in SF1. Validate the count and sum
    # of the self-join against an actual native join over the same message.
    "self": f"MATCH {PATTERN}, (m)-[:Message_hasCreator_Person]->(q:Person) WHERE {EQ} AND q.PersonId = p.PersonId RETURN {NATIVE_AGG}",
}
DDL = {
    "watch": "CREATE TEMP TABLE watch AS SELECT * FROM (VALUES " + VALUES + ") t(author)",
    "author_messages": "CREATE TEMP VIEW author_messages AS SELECT * FROM " + edges(EQ),
    "selected": "CREATE TEMP VIEW selected AS SELECT * FROM " + edges(INS),
    "lookup": "PREPARE lookup AS " + POINT.replace(str(KEYS[0]), "$author"),
}
# name -> (usage pattern, direct answer, DuckDB statement)
CASES = {
    "gql_lookup": ("P1", "point", POINT),
    "gql_fanout": ("P1", "fanout", FAN),
    "cypher_fanout": ("P1", "fanout", FAN),
    "graph_table_equality": ("P2", "fanout", "SELECT mid AS id FROM " + edges(EQ)),
    "cte_order_limit": (
        "P2/P3",
        "top",
        "WITH hits AS (SELECT mid AS id FROM " + edges(EQ) + ") SELECT id FROM hits ORDER BY id LIMIT 10",
    ),
    "view_self_join": (
        "P4/P7",
        "self",
        "SELECT count(*), sum(l.mid % 1000003) FROM author_messages l JOIN author_messages r ON l.mid = r.mid AND l.author = r.author",
    ),
    "view_exists": (
        "P5/P7",
        "exists",
        "SELECT w.author FROM watch w WHERE EXISTS (SELECT 1 FROM selected s WHERE s.author=w.author) ORDER BY w.author",
    ),
    "view_aggregate": ("P6/P7", "fan_agg", "SELECT " + AGG + " FROM author_messages"),
    "prepared_match": ("P8", "point", f"EXECUTE lookup(author := {KEYS[0]})"),
    "literal_watchlist": ("P3/P10", "groups", SQL),
    "table_watchlist": ("P3/P10", "groups", grouped(edges() + " JOIN watch w ON g.author = w.author")),
    "graph_table_in": ("P2/P6", "groups", grouped(edges(INS))),
    "arrow_reuse": ("P11", "fan_agg", FAN),
    "full_scan": ("P6", "scan", "SELECT " + AGG + " FROM " + edges()),
    "explain_only": ("P12", "plan", "EXPLAIN (FORMAT JSON) " + SQL),
}
ENGINES = ["baseline", "current", "ladybug"]


def signature(table, ordered=False):
    import hashlib

    rows = [tuple(map(int, row)) for row in zip(*(c.to_pylist() for c in table.columns))]
    if not ordered:
        rows.sort()
    return [len(rows), hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()]


def elapsed(start):
    return (perf_counter_ns() - start) / 1e6


def worker(engine, block, runs, selected, profile, package):
    from adbc_driver_manager import dbapi

    native = engine == "ladybug"
    cases = (
        list(dict.fromkeys(CASES[c][1] for c in selected if CASES[c][1] != "plan")) if native else selected
    )
    samples, checks, scans = defaultdict(list), {}, {}
    matched_watchlist_edges = None
    with ExitStack() as stack:

        def cursor():
            db = stack.enter_context(
                dbapi.connect(
                    driver=str(LIB),
                    entrypoint="duckdb_adbc_init",
                    autocommit=True,
                    db_kwargs={"allow_unsigned_extensions": "true"},
                )
            )
            return stack.enter_context(db.cursor())

        setup = perf_counter_ns()
        if native:
            import ladybug

            db = stack.enter_context(ladybug.Database(str(GRAPH), read_only=True))
            conn = stack.enter_context(ladybug.Connection(db))
        else:
            cur = cursor()
            cur.execute("SELECT library_version, source_id FROM pragma_version()")
            if cur.fetchone() != ("v2.0.1", "8d78114e90"):
                raise ValueError("Unexpected DuckDB version")
            cur.execute("LOAD " + sql_literal(package))
            cur.execute(provision(GRAPH, alias="social"))
            cur.execute("SESSION SET GRAPH social")
        setup_ms = elapsed(setup)

        def fetch(name, stmt):
            if native:
                with conn.execute(stmt) as result:
                    return result.get_as_arrow()
            cur.execute(stmt)
            table = cur.fetch_arrow_table()
            if name == "arrow_reuse":
                sink.execute("DROP TABLE IF EXISTS imported")
                sink.adbc_ingest("imported", table)
                sink.execute("SELECT " + AGG.replace("mid", "id") + " FROM imported")
                return sink.fetch_arrow_table()
            return table

        first = perf_counter_ns()
        fresh_table = fetch("point", POINT)
        first_ms = elapsed(first)
        fresh_signature = signature(fresh_table)
        if not native:
            for ddl in DDL.values():
                cur.execute(ddl)
            sink = cursor() if "arrow_reuse" in cases else None
        for iteration in range(runs + 1):
            order = cases.copy()
            random.Random(211 + 1000 * block + iteration).shuffle(order)
            for name in order:
                if not native:
                    dialect = "cypher" if name == "cypher_fanout" else "gql"
                    cur.execute(f"SET SESSION qw_graph_dialect = '{dialect}'")
                stmt = ORACLES[name] if native else CASES[name][2]
                cpu = process_time_ns()
                start = perf_counter_ns()
                table = fetch(name, stmt)
                wall_ms = elapsed(start)
                cpu_ms = (process_time_ns() - cpu) / 1e6
                oracle = name if native else CASES[name][1]
                if oracle == "plan":
                    plan = json.loads(table.column(1)[0].as_py())
                    if "QW_" not in json.dumps(plan).upper():
                        raise ValueError("Graph operator missing from EXPLAIN")
                    answer = "graph operator present"
                else:
                    answer = signature(table, ordered=oracle in ("top", "groups", "exists"))
                if native and name == "groups" and iteration == 0:
                    matched_watchlist_edges = sum(table.column("n").to_pylist())
                if checks.setdefault(name, answer) != answer:
                    raise ValueError(f"{engine} changed answer for {name}")
                if iteration:
                    samples[name].append([wall_ms, cpu_ms])
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (
            2**20 if sys.platform == "darwin" else 1024
        )
        if not native and profile:
            for name in selected:
                stmt = CASES[name][2]
                if stmt.startswith(("SELECT", "WITH")):
                    cur.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + stmt)
                    scans[name] = list(provider_rows(json.loads(cur.fetchone()[1])["operator"]))
                    if not scans[name]:
                        raise ValueError(f"No graph scan for {name}")
    return dict(
        engine=engine,
        block=block,
        setup_ms=setup_ms,
        first_point_ms=first_ms,
        first_point_result=fresh_signature,
        peak_rss_mib=peak,
        samples=samples,
        checks=checks,
        provider_rows=scans,
        matched_watchlist_edges=matched_watchlist_edges,
    )


def stats(samples):
    wall = sorted(s[0] for s in samples)
    return {
        "n": len(wall),
        "p50_ms": median(wall),
        "p95_ms": wall[math.ceil(0.95 * len(wall)) - 1],
        "cpu_ms": median(s[1] for s in samples),
    }


def main(args):
    selected = args.cases.split(",") if args.cases else list(CASES)
    if args.worker:
        print(json.dumps(worker(args.worker, args.block, args.runs, selected, args.block == 0, args.package)))
        return
    if digest(GRAPH) != GRAPH_SHA or version("ladybug") != "0.22.3":
        raise ValueError("Expected pinned SF1 graph and Ladybug 0.22.3")
    paths = dict(PACKAGES)
    packages = {}
    for engine, override in (("baseline", args.baseline), ("current", args.candidate)):
        revision, expected = PINS[engine]
        archived = PERF / f"baseline-{revision}" / "quack_weave.duckdb_extension"
        paths[engine] = override or (archived if archived.exists() else paths[engine])
        sha = digest(paths[engine])
        if override is None and sha != expected:
            raise ValueError(f"Unexpected {engine} package SHA-256: {sha}")
        packages[engine] = dict(
            sha256=sha, revision=next((rev for rev, pin in PINS.values() if pin == sha), None)
        )
    start = datetime.now(timezone.utc).isoformat()
    blocks = []
    for b in range(args.blocks):
        # Paired extension order alternates. Rotate the native reference to spread drift.
        pair = ENGINES[:2] if b % 2 == 0 else ENGINES[1::-1]
        order = pair.copy()
        order.insert([2, 0, 1][b % 3], "ladybug")
        for e in order:
            print(f"Block {b + 1}/{args.blocks} {e}", flush=True)
            call = [
                sys.executable,
                "-B",
                __file__,
                "--worker",
                e,
                "--block",
                str(b),
                "--runs",
                str(args.runs),
                "--cases",
                ",".join(selected),
            ]
            if e != "ladybug":
                call.extend(["--package", str(paths[e])])
            blocks.append(json.loads(subprocess.check_output(call, text=True)))
    ref = next(block for block in blocks if block["engine"] == "ladybug")
    if args.verify_pushdown:
        current = next(block for block in blocks if block["engine"] == "current")
        expected_scans = {"full_scan": [1], "table_watchlist": [ref["matched_watchlist_edges"]]}
        for workload, expected_rows in expected_scans.items():
            actual_rows = current["provider_rows"].get(workload)
            if actual_rows != expected_rows:
                raise ValueError(f"{workload} provider rows {actual_rows}, expected {expected_rows}")
    summary = []
    for name in selected:
        pattern, oracle, stmt = CASES[name]
        for engine in ENGINES:
            if engine == "ladybug" and oracle == "plan":
                continue
            key = oracle if engine == "ladybug" else name
            group = [b for b in blocks if b["engine"] == engine]
            expected = "graph operator present" if oracle == "plan" else ref["checks"][oracle]
            for b in group:
                if b["checks"][key] != expected or b["first_point_result"] != ref["first_point_result"]:
                    raise ValueError(f"{name}, {engine}, block {b['block']}: result mismatch")
            summary.append(
                dict(
                    workload=name,
                    pattern=pattern,
                    engine=engine,
                    **stats([s for b in group for s in b["samples"][key]]),
                    provider_rows=group[0]["provider_rows"].get(name),
                )
            )
    after = digest(GRAPH)
    if after != GRAPH_SHA:
        raise ValueError("Graph file changed")
    result = dict(
        start=start,
        finish=datetime.now(timezone.utc).isoformat(),
        graph_sha256=GRAPH_SHA,
        graph_sha256_after=after,
        graph_bytes=GRAPH.stat().st_size,
        platform=platform.platform(),
        workspace_revision=subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
        ).strip(),
        cpus=os.cpu_count(),
        packages=packages,
        duckdb="v2.0.1 8d78114e90",
        library_sha256=digest(LIB),
        versions={p: version(p) for p in ["ladybug", "pyarrow", "adbc-driver-manager"]},
        cases={c: CASES[c] for c in selected},
        native_queries=ORACLES,
        setup_sql=DDL,
        blocks=blocks,
        summary=summary,
    )
    args.out.write_text(json.dumps(result, indent=1) + "\n")
    for r in summary:
        if r["engine"] == "current":
            print(r["workload"], round(r["p50_ms"], 2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blocks", type=int, default=4)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--cases")
    parser.add_argument(
        "--verify-pushdown",
        action="store_true",
        help="Require a single aggregate row and only native-matching watchlist edges",
    )
    parser.add_argument(
        "--baseline",
        type=lambda p: Path(p).resolve(strict=True),
        help="Compare this extension package to the candidate",
    )
    parser.add_argument(
        "--candidate",
        type=lambda p: Path(p).resolve(strict=True),
        help="Measure a new package in place of the archived release",
    )
    parser.add_argument("--out", type=Path, default=HERE / "usage_regression.json")
    parser.add_argument("--worker", choices=ENGINES)
    parser.add_argument("--package", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--block", type=int, default=0)
    args = parser.parse_args()
    if min(args.blocks, args.runs) < 1:
        parser.error("Positive --blocks and --runs required")
    if (
        args.verify_pushdown
        and args.cases
        and not {"full_scan", "table_watchlist"} <= set(args.cases.split(","))
    ):
        parser.error("--verify-pushdown requires both full_scan and table_watchlist")
    main(args)
