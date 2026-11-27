"""Compare Ladybug with Quack Weave on the full LSQB SF1 graph, through Arrow fetch."""
import argparse
from contextlib import ExitStack
from hashlib import sha256
from importlib.metadata import version
import json
import math
from pathlib import Path
import platform
import random
from statistics import median
import subprocess
import sys

from adbc_driver_manager import dbapi
import numpy as np
import pyarrow as pa

import run
from engine_timing import attach_trace, check_uninstrumented, ns
from run import percentiles, publish
from watchlist import GRAPH_SHA, provision


CASES = {
    "lookup_miss": ("MATCH (p:Person) WHERE p.PersonId = -1 RETURN p.PersonId AS id", 0),
    "creator_fanout": (run.FAN, 6465),
    "friends_of_friends": (f"""MATCH (p:Person)-[:Person_knows_Person]-(f:Person)-[:Person_knows_Person]-(g:Person)
WHERE {run.EQ} AND g.PersonId <> p.PersonId
RETURN DISTINCT g.PersonId AS id ORDER BY id LIMIT 100""", 100),
    "friends_message_tags": (f"""MATCH (p:Person)-[:Person_knows_Person]-(f:Person)<-[:Message_hasCreator_Person]-(m:Message)-[:Message_hasTag_Tag]->(t:Tag)
WHERE {run.EQ}
RETURN DISTINCT t.TagId AS id ORDER BY id LIMIT 100""", 100),
    "reply_countries": ("""MATCH (reply:Message)-[:Message_replyOf_Message]->(parent:Message)-[:Message_hasCreator_Person]->(author:Person)-[:Person_isLocatedIn_City]->(city:City)-[:City_isPartOf_Country]->(country:Country)
RETURN country.CountryId AS id, count(*) AS replies ORDER BY replies DESC, id LIMIT 20""", 20),
}


def qw_statement(name):
    text = CASES[name][0]
    if name == "reply_countries":
        return f"SELECT * FROM qw_query('social','cypher',{run.sql_literal(text)},schema:='id BIGINT, replies BIGINT')"
    return text


def signature(name, table):
    names = ["id", "replies"] if name == "reply_countries" else ["id"]
    if (len(table) != CASES[name][1] or table.column_names != names or
            any(c.type != pa.int64() or c.null_count for c in table.columns)):
        raise ValueError(f"{name}: unexpected {len(table)} rows or schema {table.schema}")
    rows = np.column_stack([c.to_numpy() for c in table.columns]).astype("<i8", copy=False)
    if name == "creator_fanout":  # This is the only nonempty query without ORDER BY.
        rows.sort(axis=0)
    return sha256(rows.tobytes()).hexdigest()


def worker(args):
    import ladybug

    cases = list(CASES) if args.mixed_session else [args.case]
    direct = args.worker in ("direct", "direct_profile")
    sql = {name: CASES[name][0] if direct else qw_statement(name) for name in cases}
    rng = random.Random(1701 + args.block)
    samples = []
    rounds = []
    digests = {}
    with ExitStack() as stack:
        setup = {}
        start = ns()
        if direct:
            db = stack.enter_context(ladybug.Database(args.graph, read_only=True))
            conn = stack.enter_context(ladybug.Connection(db))
            conn.init_connection()
            setup["open_ms"] = (ns() - start) / 1e6
        else:
            db = stack.enter_context(dbapi.connect(driver=str(args.library), entrypoint="duckdb_adbc_init",
                                     autocommit=True, db_kwargs={"allow_unsigned_extensions": "true"}))
            cur = stack.enter_context(db.cursor())
            setup["open_ms"] = (ns() - start) / 1e6
            for label, statement in [
                ("threads", "SET threads=1"), ("load", "LOAD " + run.sql_literal(args.extension)),
                ("register", provision(args.graph, alias="social")), ("select_graph", "SESSION SET GRAPH social"),
                ("set_dialect", "SET SESSION qw_graph_dialect='cypher'"),
            ]:
                before = ns()
                cur.execute(statement)
                setup[label + "_ms"] = (ns() - before) / 1e6
        setup["total_ms"] = (ns() - start) / 1e6
        for i in range(2 + args.runs):
            order = cases.copy()
            if args.mixed_session:
                rng.shuffle(order)
                if samples and order[0] == samples[-1]["case"]:
                    order[0], order[1] = order[1], order[0]
            tables = []
            for name in order:
                sample = {"case": name, "round": i}
                before = ns()
                if direct:
                    with conn.execute(sql[name]) as result:
                        table = result.get_as_arrow()
                        end = ns()
                        if args.worker == "direct_profile" or not args.mixed_session:
                            sample.update(compile_ms=result.get_compiling_time(), engine_ms=result.get_execution_time())
                else:
                    cur.execute(sql[name])
                    table = cur.fetch_arrow_table()
                    end = ns()
                sample.update(start_ns=before, end_ns=end, wall_ms=(end-before)/1e6)
                samples.append(sample)
                tables.append(table)
            rounds.append({"round": i, "wall_ms": (end-samples[-len(order)]["start_ns"])/1e6})
            for name, table in zip(order, tables):
                checksum = signature(name, table)
                if digests.setdefault(name, checksum) != checksum:
                    raise ValueError(f"{name}: result changed on repetition {i}")
        if not direct:
            cur.execute("SELECT library_version, source_id FROM pragma_version()")
            if cur.fetchone() != ("v2.0.1", "8d78114e90"):
                raise ValueError("Unexpected DuckDB host")
    row = {"route": args.worker, "setup": setup, "samples": samples, "digests": digests, "rounds": rounds}
    if not args.mixed_session:
        row.update(case=args.case, digest=digests[args.case])
    return row


def print_layers(report):
    print("Warm Ladybug engine execution, native query summary (ms)")
    print("case\tdirect_p50\tdirect_p95\tqw_p50\tqw_p95\tqw_other_warm_work_p50")
    def value(summary, group, key):
        timing = summary.get(group, {}).get(key)
        return f"{timing:.3f}" if timing is not None else "—"
    for name, routes in report["summary"].items():
        direct = routes.get("direct_profile", routes["direct"])
        qw = routes.get("trace", {})
        print(name, value(direct, "engine_execution", "p50_ms"), value(direct, "engine_execution", "p95_ms"),
              value(qw, "engine_execution", "p50_ms"), value(qw, "engine_execution", "p95_ms"),
              value(qw, "other_warm_work", "p50_ms"), sep="\t")
    print("One-time session bootstrap (ms)")
    print("route\tconnections\tp50\tp95\topen_p50\tload_p50\tregister_p50")
    for route, boot in report["bootstrap_summary"].items():
        print(route, boot["n"], f"{boot['p50_ms']:.3f}", f"{boot['p95_ms']:.3f}",
              *(value(boot, "stage_p50_ms", k) for k in ("open_ms", "load_ms", "register_ms")), sep="\t")
    print("Warm client latency through Arrow fetch (ms)")
    print("case\tdirect_p50\tdirect_p95\tqw_p50\tqw_p95")
    for name, routes in report["summary"].items():
        print(name, *(f"{routes[route][metric]:.3f}" for route in ("direct", "qw") for metric in ("p50_ms", "p95_ms")), sep="\t")
    if "session_summary" in report:
        print("Five queries on one connection (ms)")
        print("route\twarm_round_p50\twarm_round_p95\tnative_execution_sum_p50\tnative_execution_sum_p95")
        for route, profile in (("direct", "direct_profile"), ("qw", "trace")):
            session = report["session_summary"][route]
            diag = report["session_summary"].get(profile, {})
            print(route, f"{session['warm_round_p50_ms']:.3f}", f"{session['warm_round_p95_ms']:.3f}",
                  value(diag, "engine_execution", "p50_ms"), value(diag, "engine_execution", "p95_ms"), sep="\t")


def collect(args):
    if version("ladybug") != "0.22.3" or run.digest(args.graph) != GRAPH_SHA:
        raise ValueError("Expected the pinned Ladybug client and the original SF1 graph")
    if args.blocks < 2 or args.blocks % 2 or args.runs < 1:
        raise ValueError("Use a positive run count and an even number of blocks >= 2")
    routes = ["direct", "qw"] + (["trace"] if args.phase_extension else [])
    if args.mixed_session:
        routes.append("direct_profile")
    report = {"platform": platform.platform(), "python": platform.python_version(), "graph_sha256": GRAPH_SHA,
              "versions": {p: version(p) for p in ("ladybug", "pyarrow", "adbc-driver-manager")},
              "extension_sha256": run.digest(args.extension), "duckdb_sha256": run.digest(args.library),
              "workloads": {k: {"cypher": q, "qw_sql": qw_statement(k), "rows": n} for k, (q,n) in CASES.items()},
              "blocks": args.blocks, "warmups": 2, "runs": args.runs, "workers": [], "summary": {}}
    if args.phase_extension:
        report["phase_extension_sha256"] = run.digest(args.phase_extension)
    expected = {}
    if args.mixed_session:
        report["connection_mode"] = "mixed_sequential"
    for block in range(args.blocks):
        cases = [None] if args.mixed_session else list(CASES)
        random.Random(4026 + block).shuffle(cases)
        for name in cases:
            for route in (routes if block % 2 == 0 else routes[::-1]):
                ext = args.phase_extension if route == "trace" else args.extension
                command = [sys.executable, "-B", __file__, "--worker", route, "--block", str(block), "--graph", args.graph,
                           "--library", args.library, "--extension", ext, "--runs", str(args.runs)]
                command.extend(["--mixed-session"] if args.mixed_session else ["--case", name])
                result = subprocess.run(command, capture_output=True, text=True, timeout=300)
                if result.returncode:
                    raise RuntimeError(f"{route} {name}: {result.stderr}")
                row = json.loads(result.stdout)
                for case, digest in row["digests"].items():
                    if expected.setdefault(case, digest) != digest:
                        raise ValueError(f"{route} {case}: rows differ between clients")
                if route == "trace":
                    attach_trace(row["samples"], result.stderr)
                elif route == "qw":
                    check_uninstrumented(result.stderr)
                row["block"] = block
                report["workers"].append(row)
        print(f"Verified block {block + 1}/{args.blocks}", flush=True)
    for name in CASES:
        report["summary"][name] = {}
        for route in routes:
            workers = [w for w in report["workers"] if w["route"] == route and name in w["digests"]]
            series = [[s for s in w["samples"] if s["case"] == name] for w in workers]
            hot = [s for observations in series for s in observations[2:]]
            summary = {**percentiles(s["wall_ms"] for s in hot),
                       "setup_ms": median(w["setup"]["total_ms"] for w in workers),
                       "first_query_ms": median(observations[0]["wall_ms"] for observations in series)}
            for field in ("engine_ms", "compile_ms", "before_native_ms", "native_call_ms", "after_native_ms"):
                if field in hot[0]:
                    summary[field] = median(s[field] for s in hot)
            if "engine_ms" in hot[0]:
                summary["engine_execution"] = percentiles(s["engine_ms"] for s in hot)
            if route == "trace":
                summary["engine_share_pct"] = median(100*s["engine_ms"]/s["wall_ms"] for s in hot)
                summary["other_warm_work"] = percentiles(s["wall_ms"] - s["engine_ms"] for s in hot)
            report["summary"][name][route] = summary
    report["bootstrap_summary"] = {}
    for route in ("direct", "qw"):
        setups = [w["setup"] for w in report["workers"] if w["route"] == route]
        report["bootstrap_summary"][route] = {
            **percentiles(s["total_ms"] for s in setups),
            "stage_p50_ms": {k: median(s[k] for s in setups) for k in setups[0] if k != "total_ms"},
        }
    if args.mixed_session:
        report["session_summary"] = {}
        for route in routes:
            workers = [w for w in report["workers"] if w["route"] == route]
            hot = sorted(r["wall_ms"] for w in workers for r in w["rounds"][2:])
            totals = [w["setup"]["total_ms"] + sum(r["wall_ms"] for r in w["rounds"]) for w in workers]
            report["session_summary"][route] = {
                "connections": len(workers), "queries_per_connection": len(CASES)*(args.runs+2),
                "setup_p50_ms": median(w["setup"]["total_ms"] for w in workers),
                "setup_plus_first_round_p50_ms": median(w["setup"]["total_ms"] + w["rounds"][0]["wall_ms"] for w in workers),
                "warm_rounds": len(hot), "warm_round_p50_ms": median(hot),
                "warm_round_p95_ms": hot[math.ceil(.95*len(hot))-1], "session_total_p50_ms": median(totals),
                "setup_share_p50_pct": median(100*w["setup"]["total_ms"]/t for w,t in zip(workers,totals)),
            }
            if route in ("direct_profile", "trace"):
                # Sum the native timers within each observed round before taking percentiles.
                engine_rounds = []
                for w in workers:
                    for r in w["rounds"][2:]:
                        engine_rounds.append(sum(s["engine_ms"] for s in w["samples"] if s["round"] == r["round"]))
                report["session_summary"][route]["engine_execution"] = percentiles(engine_rounds)
    if run.digest(args.graph) != GRAPH_SHA:
        raise ValueError("Graph changed during the run")
    publish(args.out, report)
    print_layers(report)
    print(args.out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, default=run.ROOT / "build/perf/lsqb-sf1/sf1.lbdb")
    parser.add_argument("--library", type=Path, default=run.LIB)
    parser.add_argument("--extension", type=Path, default=run.EXT)
    parser.add_argument("--phase-extension", type=Path, help="Optional diagnostic build emitting QW_PHASE events")
    parser.add_argument("--blocks", type=int, default=6)
    parser.add_argument("--runs", type=int, default=8)
    parser.add_argument("--mixed-session", action="store_true",
                        help="Execute all five queries sequentially on one connection per block and client")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--worker", choices=("direct", "direct_profile", "qw", "trace"), help=argparse.SUPPRESS)
    parser.add_argument("--case", choices=CASES, help=argparse.SUPPRESS)
    parser.add_argument("--block", type=int, default=0, help=argparse.SUPPRESS)
    options = parser.parse_args()
    options.graph = options.graph.resolve(strict=True)
    options.library = options.library.resolve(strict=True)
    options.extension = options.extension.resolve(strict=True)
    if options.phase_extension:
        options.phase_extension = options.phase_extension.resolve(strict=True)
    if options.worker:
        print(json.dumps(worker(options)))
    elif options.out:
        collect(options)
    else:
        parser.error("--out is required")
