"""Rank sales channels for a creator using a graph portfolio and a separate settlement ledger."""
import argparse
from collections import defaultdict
from contextlib import ExitStack
from datetime import date, timedelta
from importlib.metadata import version
import json
from pathlib import Path
import platform
import random
from statistics import median
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as csv
import pyarrow.parquet as pq

import run
from engine_timing import attach_trace, check_uninstrumented, ns
from tracker import percentiles, publish, verify_fixture


CLOSE = date(2025, 4, 1)  # Exclusive, for both reporting windows.
WINDOWS = (7, 30)
CHANNELS = ("affiliate", "email", "livestream", "marketplace", "paid_social", "storefront")
FACTS = {"parquet": "read_parquet('sales.parquet')", "memory": "sales_memory"}
ROUTES = ("gql", "cypher", "native_arrow", "cached_arrow")
GRAPH = ("MATCH (m:Message)-[:Message_hasCreator_Person]->(p:Person) "
         f"WHERE p.PersonId = {run.KEYS[0]} RETURN m.MessageId AS content_id")
BRIDGE = ("qw_query(current_setting('qw_selected_graph'), current_setting('qw_graph_dialect'), "
          + run.sql_literal(GRAPH) + ", schema := 'content_id BIGINT')")
SEED = 40261


def sql(graph, storage, days):
    return f"""SELECT s.channel, count(*) FILTER (WHERE s.kind = 'sale') AS sales,
       sum(s.amount_cents)::BIGINT AS net_sales_cents
FROM {graph} AS g
JOIN {FACTS[storage]} AS s USING (content_id)
WHERE s.status = 'settled' AND s.booked_on >= DATE '{CLOSE - timedelta(days=days)}'
  AND s.booked_on < DATE '{CLOSE}'
GROUP BY s.channel
HAVING count(*) FILTER (WHERE s.kind = 'sale') >= 5 AND sum(s.amount_cents) > 0
ORDER BY net_sales_cents DESC, s.channel ASC
LIMIT 3"""


def make_ledger(path, mids, orders):
    """Each purchase has one post. A settled purchase can later have one partial refund."""
    rng = np.random.default_rng(SEED)
    content = rng.choice(mids, orders)
    channel = rng.choice(CHANNELS, orders, p=[.12, .21, .17, .19, .23, .08])
    day = rng.integers(0, 90, orders)
    cents = rng.integers(500, 25_001, orders)
    status = rng.choice(["settled", "pending", "void"], orders, p=[.88, .08, .04])
    refunds = np.flatnonzero((status == "settled") & (rng.random(orders) < .14))
    n = len(refunds)
    days = np.concatenate([day, day[refunds] + rng.integers(1, 15, n)])
    ids = np.arange(orders, dtype=np.int64)
    table = pa.table({
        "order_id": np.concatenate([ids, ids[refunds]]),
        "content_id": np.concatenate([content, content[refunds]]),
        "channel": np.concatenate([channel, channel[refunds]]),
        "booked_on": np.datetime64(CLOSE - timedelta(days=90)) + days.astype("timedelta64[D]"),
        "kind": np.concatenate([np.full(orders, "sale"), np.full(n, "refund")]),
        "status": np.concatenate([status, rng.choice(["settled", "pending"], n, p=[.9, .1])]),
        "amount_cents": np.concatenate([cents, -rng.integers(1, cents[refunds] + 1)]),
    })
    # Daily clustering lets a Parquet reader skip row groups outside the reporting period.
    pq.write_table(table.take(np.argsort(days, kind="stable")), path, compression="zstd", row_group_size=32768)


def oracle(path, portfolio):
    groups = {days: defaultdict(lambda: [0, 0]) for days in WINDOWS}
    funnel = {days: {"sales": 0, "refunds": 0, "gross_cents": 0, "refunded_cents": 0} for days in WINDOWS}
    matched = 0
    for batch in pq.ParquetFile(path).iter_batches():
        selected = batch.filter(pc.is_in(batch["content_id"], value_set=portfolio))
        matched += len(selected)
        for row in selected.to_pylist():
            if row["status"] != "settled":
                continue
            age = (CLOSE - row["booked_on"]).days
            for days, totals in groups.items():
                if 1 <= age <= days:
                    values = totals[row["channel"]]
                    values[0] += row["kind"] == "sale"
                    values[1] += row["amount_cents"]
                    if row["kind"] == "sale":
                        funnel[days]["sales"] += 1
                        funnel[days]["gross_cents"] += row["amount_cents"]
                    else:
                        funnel[days]["refunds"] += 1
                        funnel[days]["refunded_cents"] -= row["amount_cents"]
    expected = {}
    for days, totals in groups.items():
        eligible = [[c, sales, net] for c, (sales, net) in totals.items() if sales >= 5 and net > 0]
        expected[str(days)] = sorted(eligible, key=lambda row: (-row[2], row[0]))[:3]
    return expected, {"portfolio_ledger_events": matched, "settled_by_window": funnel}


def direct_reader(stack, a, diagnostic):
    path = a.fixture / run.ENGINES[a.provider]
    if a.provider == "ladybug":
        import ladybug
        db = stack.enter_context(ladybug.Database(str(path), read_only=True))
        conn = stack.enter_context(ladybug.Connection(db))

        def read():
            with conn.execute(GRAPH) as result:
                return result.get_as_arrow(), result.get_execution_time() if diagnostic else None
    else:
        from relate import Database
        db = Database(str(path), read_only=True)
        stack.callback(db.close)

        def read():
            if diagnostic:
                result = db.execute(GRAPH)
                return pa.Table.from_pylist(result.data), result.execute_ms
            return pa.ipc.open_stream(db.execute_arrow(GRAPH)).read_all(), None
    return read


def worker(request):
    a = SimpleNamespace(**request)
    a.fixture, a.library, a.extension = map(Path, (a.fixture, a.library, a.extension))
    hybrid = a.route in ("cypher", "gql")
    with ExitStack() as stack:
        if hybrid:
            cur, setup = stack.enter_context(run.cursor(a, prepare_watchlist=False))
            start = ns()
            cur.execute("SET SESSION qw_graph_dialect = " + run.sql_literal(a.route))
            setup["set_dialect_ms"] = (ns() - start) / 1e6
        else:
            cur, setup = stack.enter_context(run.duckdb_cursor(a))
            start = ns()
            read = direct_reader(stack, a, a.diagnostic)
            setup["native_open_ms"] = (ns() - start) / 1e6
        bootstrap = sum(setup.values())
        start = ns()
        cur.execute("CREATE TEMP TABLE sales_memory AS FROM read_parquet('sales.parquet')")
        preload = (ns() - start) / 1e6
        cache_ms = None
        if a.route == "cached_arrow":
            start = ns()
            ids, _ = read()
            cur.adbc_ingest("creator_content", ids, mode="replace")
            cache_ms = (ns() - start) / 1e6

        queries = {(storage, days): sql(BRIDGE if hybrid else "creator_content", storage, days)
                   for storage in FACTS for days in WINDOWS}
        samples = []
        for rep in range(a.runs + 1):
            order = list(queries)
            random.Random(SEED + a.block * 100 + rep).shuffle(order)
            for storage, days in order:
                sample = {"storage": storage, "days": days, "rep": rep}
                start = ns()
                if a.route == "native_arrow":
                    ids, engine_ms = read()
                    fetched = ns()
                    cur.adbc_ingest("creator_content", ids, mode="replace")
                    ingested = ns()
                cur.execute(queries[storage, days])
                result = cur.fetch_arrow_table()
                end = ns()
                sample.update(start_ns=start, end_ns=end, wall_ms=(end - start) / 1e6)
                if a.route == "native_arrow":
                    sample.update(graph_fetch_ms=(fetched - start) / 1e6, handoff_ms=(ingested - fetched) / 1e6,
                                  sql_fetch_ms=(end - ingested) / 1e6)
                    if a.diagnostic:
                        sample["engine_ms"] = engine_ms
                rows = [list(row) for row in zip(*(col.to_pylist() for col in result.columns))]
                if result.column_names != ["channel", "sales", "net_sales_cents"] or rows != a.expected[str(days)]:
                    raise ValueError(f"{a.provider}/{a.route}/{storage}/{days} returned {rows}")
                samples.append(sample)

        # The dedicated diagnostic worker emits exactly one native event per timed submission.
        if not a.diagnostic:
            if hybrid:
                cur.execute("SELECT * FROM " + BRIDGE)
                ids = cur.fetch_arrow_table()
            if ids.column_names != ["content_id"] or run.signature([ids.column(0).to_numpy()]) != a.portfolio:
                raise ValueError("Graph portfolio differs from the source edge CSV")
        return {"setup": setup, "bootstrap_ms": bootstrap, "memory_preload_ms": preload,
                "cache_build_ms": cache_ms, "samples": samples}


def measure(request, folder):
    result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--worker"],
                            input=json.dumps(request), cwd=folder, capture_output=True, text=True, timeout=300)
    if result.returncode:
        raise RuntimeError(f"{request['provider']}/{request['route']}: {result.stderr}")
    row = json.loads(result.stdout)
    if request["diagnostic"] and request["route"] in ("gql", "cypher"):
        attach_trace(row["samples"], result.stderr, request["provider"])
    else:
        check_uninstrumented(result.stderr)
    return row


def summarize(workers):
    series = defaultdict(lambda: defaultdict(list))
    for w in workers:
        for s in w["samples"]:
            if s["rep"] == 0:
                continue
            group = series[w["provider"], w["route"], s["storage"], s["days"]]
            if w["diagnostic"]:
                group["engine_ms"].append(s["engine_ms"])
            else:
                for field in ("wall_ms", "graph_fetch_ms", "handoff_ms", "sql_fetch_ms"):
                    if field in s:
                        group[field].append(s[field])
    return [{"provider": p, "route": route, "storage": storage, "days": days,
             **{field: percentiles(values) for field, values in timings.items()}}
            for (p, route, storage, days), timings in sorted(series.items())]


def write_report(folder, report):
    n, _ = report["portfolio"]
    ledger = report["ledger"]
    lines = ["# Creator partnership review", "",
             f"Creator {report['creator_id']} has {n:,} posts. The synthetic USD ledger contains "
             f"{ledger['events']:,} events on {ledger['orders']:,} orders. "
             f"{report['funnel']['portfolio_ledger_events']:,} events reference the creator’s posts.", "",
             "## Ranked channels", "",
             "| Window | Channel | Settled purchases | Net sales (USD) |", "|---|---|---:|---:|"]
    for days in WINDOWS:
        for channel, sales, cents in report["expected"][str(days)]:
            lines.append(f"| {days} days | {channel} | {sales:,} | {cents / 100:,.2f} |")
    lines += ["", "## Warm query latency", "",
              f"Cells show p50 / p95 in milliseconds, from submission through the full result fetch. "
              f"Each cell includes {report['blocks'] * report['runs']} warm observations.", "",
              "| Provider | Ledger | Days | Live GQL | Live Cypher | Direct + fresh Arrow | Reused portfolio |",
              "|---|---|---:|---:|---:|---:|---:|"]
    series = {(s["provider"], s["storage"], s["days"], s["route"]): s for s in report["summary"]}
    for p in run.ENGINES:
        for storage in FACTS:
            for days in WINDOWS:
                timings = [series[p, storage, days, route]["wall_ms"] for route in ROUTES]
                cells = " | ".join(f"{t['p50_ms']:.2f} / {t['p95_ms']:.2f}" for t in timings)
                lines.append(f"| {p} | {storage} | {days} | {cells} |")
    lines += ["", "## One-time setup", "",
              "Medians in milliseconds. The portfolio copy belongs to the reused-portfolio route. "
              "The memory preload reads the same Parquet ledger once per connection.", "",
              "| Provider | Route | Connection bootstrap | Memory preload | Portfolio copy |",
              "|---|---|---:|---:|---:|"]
    for p in run.ENGINES:
        for route in ROUTES:
            ws = [w for w in report["workers"] if w["provider"] == p and w["route"] == route and not w["diagnostic"]]
            cache = f"{median(w['cache_build_ms'] for w in ws):.2f}" if route == "cached_arrow" else "—"
            lines.append(f"| {p} | {route} | {median(w['bootstrap_ms'] for w in ws):.2f} | "
                         f"{median(w['memory_preload_ms'] for w in ws):.2f} | {cache} |")
    lines += ["", "Each live query returns its ranked rows to the application. The fresh direct route also passes "
              f"{n:,} post IDs through the application on every submission. The cached route pays that cost once "
              "and uses the captured portfolio for both windows.", "",
              "The JSON contains the exact SQL, row oracles, raw timings, direct fetch and transfer timings, "
              "and native execution counters when the timing companion was supplied. [Measurements](report.json)"]
    (folder / "report.md").write_text("\n".join(lines) + "\n")


def collect(a, folder):
    manifest = json.loads((a.fixture / "fixture.json").read_text())
    verify_fixture(a.fixture, manifest)
    edges = csv.read_csv(a.fixture / "edges.csv")
    portfolio = edges["mid"].filter(pc.equal(edges["author"], run.KEYS[0])).combine_chunks()
    if not len(portfolio) or pc.count_distinct(portfolio).as_py() != len(portfolio):
        raise ValueError("Expected a nonempty portfolio with one creator edge per post")
    path = folder / "sales.parquet"
    make_ledger(path, edges["mid"].to_numpy(), a.orders)
    expected, funnel = oracle(path, portfolio)
    signature = run.signature([portfolio.to_numpy()])
    versions = {p: version(p) for p in ("numpy", "pyarrow", "adbc-driver-manager", "ladybug", "relate-db")}
    report = {"scenario": "creator_channel_review", "platform": platform.platform(), "versions": versions,
              "fixture": manifest, "graph_edges": len(edges), "creator_id": run.KEYS[0], "portfolio": signature,
              "ledger": {"orders": a.orders, "events": pq.ParquetFile(path).metadata.num_rows, "sha256": run.digest(path),
                         "bytes": path.stat().st_size, "seed": SEED, "close_exclusive": CLOSE.isoformat()},
              "expected": expected, "funnel": funnel, "graph_query": GRAPH, "hybrid_sql": {
                  f"{storage}_{days}d": sql(BRIDGE, storage, days) for storage in FACTS for days in WINDOWS},
              "blocks": a.blocks, "runs": a.runs, "warmups": 1, "duckdb_threads": 1,
              "release_sha256": run.digest(a.extension), "host_sha256": run.digest(a.library), "workers": []}
    if a.phase_extension:
        report["phase_sha256"] = run.digest(a.phase_extension)
    del edges
    for block in range(a.blocks):
        subjects = [(p, route) for p in run.ENGINES for route in ROUTES]
        # Reverse the whole schedule in the paired block. Both providers see each route order.
        for provider, route in subjects[::1 if block % 2 == 0 else -1]:
            for diagnostic in ([False, True] if a.phase_extension and route != "cached_arrow" else [False]):
                extension = a.phase_extension if diagnostic else a.extension
                key = dict(block=block, provider=provider, route=route, diagnostic=diagnostic)
                request = {**key, "fixture": str(a.fixture), "library": str(a.library), "extension": str(extension),
                           "expected": expected, "portfolio": signature, "runs": a.runs}
                report["workers"].append({**key, **measure(request, folder)})
        print(f"Verified block {block + 1}/{a.blocks}", flush=True)
    verify_fixture(a.fixture, manifest)
    if run.digest(path) != report["ledger"]["sha256"]:
        raise ValueError("Settlement ledger changed during the run")
    report["summary"] = summarize(report["workers"])
    publish(folder / "report.json", report)
    write_report(folder, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=run.BUILD / "mod1")
    parser.add_argument("--library", type=Path, default=run.LIB)
    parser.add_argument("--extension", type=Path, default=run.EXT)
    parser.add_argument("--phase-extension", type=Path, help="Matching diagnostic build for native execution counters")
    parser.add_argument("--orders", type=int, default=1_000_000)
    parser.add_argument("--blocks", type=int, default=4)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--out", type=Path, help="New directory for sales.parquet, report.json and report.md")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(json.load(sys.stdin)), allow_nan=False))
    else:
        if not args.out or args.out.exists() or args.blocks < 2 or args.blocks % 2 or min(args.orders, args.runs) < 1:
            parser.error("Choose a new output directory, positive order/run counts and an even block count >= 2")
        args.fixture, args.library, args.extension = (p.resolve(strict=True) for p in (args.fixture, args.library, args.extension))
        if args.phase_extension:
            args.phase_extension = args.phase_extension.resolve(strict=True)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=args.out.parent) as temp:
            collect(args, Path(temp))
            Path(temp).rename(args.out)
        print(args.out / "report.json")
