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
from tempfile import TemporaryDirectory
from time import perf_counter_ns, process_time_ns
from uuid import uuid4

import pyarrow as pa

import application_workloads as application
from engine_timing import attach_trace, check_uninstrumented, ns
import micro_workloads as micro
import run
import session_lookups as lookup
import workload_manifest
from planning.compare import OUTER, VIA_VIEW
from run import percentiles, publish, verify_fixture
from watchlist import SQL as VALUES_JOIN


# A case names one logical workload. Each direct baseline uses native Cypher.
MICRO_CASES = {name: (sql, name) for name, sql in workload_manifest.micro_statements().items()}
APPLICATION_CASES = {name: (sql, name) for name, sql in application.statements().items()}
MICRO_HOST_ROUTE = application.HOST_ROUTE
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
    **MICRO_CASES,
    **APPLICATION_CASES,
}
CASES = {**STANDALONE, **HYBRID}
PREPARED_ROUTE = "qw_prepared_cypher"
ROUTES = {"direct_cypher": STANDALONE, "qw_gql": STANDALONE,
          "qw_cypher": STANDALONE, PREPARED_ROUTE: STANDALONE, "qw_pgq": HYBRID,
          MICRO_HOST_ROUTE: {**MICRO_CASES, **APPLICATION_CASES},
          application.STAGED_ROUTE: {name: APPLICATION_CASES[name] for name in application.STAGED}}
HISTORY = run.BUILD / "tracker"
PROTOCOL = 2


def schedule(cases, block, runs):
    series = []
    for repetition in range(runs + 1):
        names = list(cases)
        random.Random(7411 + 101 * block + repetition).shuffle(names)
        series.extend((repetition, name) for name in names)
    return series


def replay_schedule(providers, routes, blocks, runs):
    planned = []
    for block in range(blocks):
        order = 1 if block % 2 == 0 else -1
        for provider in providers[::order]:
            for route in list(routes)[::order]:
                if routes[route]:
                    planned.append({"provider": provider, "route": route, "block": block,
                                    "sequence": [{"case": case, "repetition": repetition}
                                                 for repetition, case in schedule(routes[route], block, runs)]})
    return planned


def check_result(expected, name, actual):
    if actual != expected[CASES[name][1]]:
        raise ValueError(f"{name}: incorrect result; expected {expected[CASES[name][1]]}, got {actual}")


def prepared_sql(name):
    alias = run.sql_literal(run.GRAPH_ALIAS)
    statement = run.sql_literal(STANDALONE[name][0])
    return f"SELECT * FROM qw_query({alias}, 'cypher', {statement}, schema := 'id BIGINT')"


def fetch_table(fetch, statement, *, expected_schema=None, require_lookup_schema=False, diagnostic=False, ordered=False):
    cpu = process_time_ns()
    start = perf_counter_ns()
    if diagnostic:
        trace_start = ns()
    table = fetch(statement)
    if diagnostic:
        trace_end = ns()
    timing = {"wall_ms": run.milliseconds(start), "cpu_ms": (process_time_ns() - cpu) / 1e6}
    if diagnostic:
        timing.update(start_ns=trace_start, end_ns=trace_end)
    if require_lookup_schema and (table.column_names != ["id"] or table["id"].type != pa.int64()):
        raise ValueError(f"Expected one BIGINT id column, got {table.schema}")
    if expected_schema is not None:
        duckdb_types = {pa.int64(): "BIGINT", pa.string(): "VARCHAR", pa.large_string(): "VARCHAR"}
        actual_schema = [[field.name, duckdb_types.get(field.type, str(field.type))] for field in table.schema]
        if actual_schema != expected_schema:
            raise ValueError(f"Unexpected Hybrid Query result schema: {actual_schema}, expected {expected_schema}")
    if ordered:
        return application.signature([list(row.values()) for row in table.to_pylist()]), timing
    for column in table.columns:
        if column.null_count or not (pa.types.is_integer(column.type) or
                                     (pa.types.is_decimal(column.type) and column.type.scale == 0)):
            raise ValueError(f"Expected non-null integers from this SF1 workload, got {table.schema}")
    return run.signature([c.to_numpy(zero_copy_only=False) for c in table.columns]), timing


def python_worker(a, request):
    sequence = schedule(request["cases"], a.block, a.runs)
    statements = {name: CASES[name][0] for name in request["cases"]}
    session_lookups = request.get("session_lookups", False)
    diagnostic = request.get("diagnostic", False)
    native_summary = {}
    application_parameters = request.get("application_parameters", {})
    record_replay = "micro_relations" in request or bool(application_parameters)
    with ExitStack() as stack:
        if a.route == "direct_cypher" and a.provider == "relate":
            from relate import Database
            start = perf_counter_ns()
            db = Database(str(a.fixture / run.ENGINES["relate"]), read_only=True)
            stack.callback(db.close)
            setup = {"open_ms": run.milliseconds(start)}

            def fetch(statement):
                if diagnostic:
                    result = db.execute(statement)
                    if result.columns != ["id"]:
                        raise ValueError(f"Unexpected direct RelateDB columns: {result.columns}")
                    native_summary.update(engine_ms=result.execute_ms, parse_ms=result.parse_ms, plan_ms=result.plan_ms)
                    return pa.table({"id": pa.array([row["id"] for row in result.data], type=pa.int64())})
                table = pa.ipc.open_stream(db.execute_arrow(statement)).read_all()
                if table.column_names != ["id"]:
                    raise ValueError(f"Unexpected direct RelateDB schema: {table.schema}")
                # The wheel reports string for an empty, untyped Cypher result.
                return table if table.num_rows else table.cast(pa.schema([("id", pa.int64())]))
        elif a.route in ("direct_cypher", lookup.DIRECT_PREPARED, lookup.DIRECT_PARAM):
            import ladybug
            start = perf_counter_ns()
            db = stack.enter_context(ladybug.Database(a.fixture / run.ENGINES["ladybug"], read_only=True))
            conn = stack.enter_context(ladybug.Connection(db))
            setup = {"open_ms": run.milliseconds(start)}

            def fetch(statement):
                with conn.execute(statement) as result:
                    table = result.get_as_arrow()
                    if diagnostic:
                        native_summary.update(engine_ms=result.get_execution_time(), compile_ms=result.get_compiling_time())
                    return table
            if a.route != "direct_cypher":
                fetch = lookup.prepare_fetch(stack, a.route, conn, statements, setup)
        else:
            cur, setup = stack.enter_context(run.cursor(a))
            if a.route != PREPARED_ROUTE or session_lookups:
                dialect = ("gql" if a.route in ("qw_gql", "qw_pgq", MICRO_HOST_ROUTE, application.STAGED_ROUTE)
                           else "cypher")
                start = perf_counter_ns()
                cur.execute("SET SESSION qw_graph_dialect = " + run.sql_literal(dialect))
                setup["set_dialect_ms"] = run.milliseconds(start)
            if "view_where" in request["cases"]:
                cur.execute("CREATE TEMP VIEW planning_pairs AS SELECT * FROM " + run.PAIRS)
            if "micro_relations" in request:
                micro.setup(cur, request["micro_relations"], prefilter=a.route != MICRO_HOST_ROUTE)
            if application_parameters:
                start = perf_counter_ns()
                for name, parameters in application_parameters.items():
                    directory = Path(request["application_directory"]) / name
                    for statement in application.setup_sql(
                        application.CASES[name], parameters, directory, a.route != MICRO_HOST_ROUTE,
                    ):
                        cur.execute(statement)
                    if a.route == application.STAGED_ROUTE:
                        application.CASES[name].setup_staged(cur)
                setup["application_setup_ms"] = run.milliseconds(start)

            def fetch(statement):
                cur.execute(statement)
                return cur.fetch_arrow_table()

            if a.route == PREPARED_ROUTE:
                statements = {name: prepared_sql(name) for name in statements}
            if a.route == PREPARED_ROUTE or a.route in lookup.CONTROLS:
                fetch = lookup.prepare_fetch(stack, a.route, cur.connection, statements, setup)

        setup["bootstrap_ms"] = sum(
            setup[key] for key in ("open_ms", "threads_ms", "load_ms", "register_ms",
                                   "select_graph_ms", "set_dialect_ms", "application_setup_ms") if key in setup
        )
        schemas = request.get("schemas", {})
        samples = []
        for repetition, name in sequence:
            case = application.CASES.get(name)
            reader = fetch
            if hasattr(case, "execute"):
                def reader(_):
                    return case.execute(cur, application_parameters[name])
            actual, timing = fetch_table(reader, statements[name], expected_schema=schemas.get(name),
                                         require_lookup_schema=session_lookups, diagnostic=diagnostic,
                                         ordered=name in application_parameters)
            check_result(request["expected"], name, actual)
            if record_replay:
                timing.update(result_rows=int(actual[0]), result_sha256=actual[1])
            samples.append({"repetition": repetition, "case": name, **timing, **native_summary})
        worker = {"setup": setup, "samples": samples,
                  "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (2**20 if sys.platform == "darwin" else 1024)}
        if a.route in (lookup.LIVE, lookup.FIXED):
            worker["session_probe"] = lookup.probe_session(cur, a.route)
        if a.route in ("qw_pgq", MICRO_HOST_ROUTE, application.STAGED_ROUTE):
            crossings = {}
            if record_replay:
                cur.execute("CALL enable_logging(level = 'info')")
                worker["scan_diagnostics"] = {}
            for name in request["cases"]:
                case = application.CASES.get(name)
                if hasattr(case, "diagnose"):
                    diagnostic = case.diagnose(cur, application_parameters[name], scan_diagnostic)
                    crossings[name] = diagnostic["scan_rows"]
                    worker["scan_diagnostics"][name] = diagnostic
                    continue
                if record_replay:
                    cur.execute("CALL truncate_duckdb_logs()")
                cur.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + statements[name])
                scans = list(run.provider_rows(json.loads(cur.fetchone()[1])["operator"]))
                if a.route == application.STAGED_ROUTE:
                    if scans:
                        raise ValueError(f"Staged benchmark query {name} still reads the provider")
                    crossings[name] = 0
                else:
                    (crossings[name],) = scans
                if record_replay:
                    worker["scan_diagnostics"][name] = scan_diagnostic(cur, crossings[name])
            worker["graph_scan_rows"] = crossings
        return worker


def scan_diagnostic(cursor, rows):
    kinds = ("QuackWeaveGraphRoute", "QuackWeaveGraphAdmission", "QuackWeaveWatchlist")
    cursor.execute("SELECT type, message FROM duckdb_logs() WHERE type IN ("
                   + ", ".join(map(run.sql_literal, kinds)) + ") ORDER BY type, message")
    events = {kind: [] for kind in kinds}
    for kind, message in cursor.fetchall():
        events[kind].append(message)
    applied, admission, offers = (events[kind] for kind in kinds)
    diagnostic = {"scan_rows": rows, "watchlist_offers": offers}
    unavailable = {}
    for field, messages in (("applied_route", applied), ("admitted_generation", admission)):
        diagnostic[field] = messages[0] if len(messages) == 1 else None
        if len(messages) != 1:
            unavailable[field] = "no log entry" if not messages else "multiple log entries for one scan"
    if unavailable:
        diagnostic["unavailable"] = unavailable
    return diagnostic


def run_process(command, payload, timeout):
    result = subprocess.run(command, input=payload, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"Benchmark worker exited {result.returncode}: {result.stderr.strip()}")
    return result


def measure_worker(a, provider, route, block, cases, expected):
    command = [sys.executable, "-B", __file__, "_worker", "--provider", provider, "--route", route,
               "--fixture", a.fixture, "--extension", a.extension, "--library", a.library,
               "--runs", str(a.runs), "--block", str(block)]
    payload = {"expected": expected, "cases": cases, "session_lookups": a.session_lookups}
    if getattr(a, "micro", False):
        payload["micro_relations"] = a.micro_relations
        payload["schemas"] = {name: a.micro_cases[name]["result_schema"] for name in cases}
    if a.hybrid:
        payload["application_directory"] = str(a.application_directory)
        payload["application_parameters"] = {name: a.application_parameters[name] for name in cases}
        payload["schemas"] = {name: application.CASES[name].SCHEMA for name in cases}
    release = run_process(command, json.dumps(payload), a.timeout)
    check_uninstrumented(release.stderr)
    measured = json.loads(release.stdout)
    if route == "direct_cypher" or (a.phase_extension and route in ("qw_gql", "qw_cypher")):
        if route != "direct_cypher":
            command[command.index("--extension") + 1] = a.phase_extension
        diagnostic = run_process(command, json.dumps({**payload, "diagnostic": True}), a.timeout)
        samples = json.loads(diagnostic.stdout)["samples"]
        if route != "direct_cypher":
            attach_trace(samples, diagnostic.stderr, provider)
        measured["engine_samples"] = samples
    return {"block": block, "provider": provider, "route": route, **measured}


def summarize_bootstrap(workers):
    groups = {}
    for w in workers:
        groups.setdefault((w["provider"], w["route"]), []).append(w["setup"])
    return [{"provider": provider, "route": route, **percentiles(s["bootstrap_ms"] for s in setups),
             "stage_p50_ms": {k: median(s[k] for s in setups) for k in setups[0]
                              if k.endswith("_ms") and k not in ("bootstrap_ms", "prepare_ms")}}
            for (provider, route), setups in sorted(groups.items())]


def summarize(workers):
    series = {}
    engine = {}
    for worker in workers:
        for sample in worker["samples"]:
            key = (worker["provider"], worker["route"], sample["case"])
            if sample["repetition"]:
                series.setdefault(key, []).append(sample)
        for sample in worker.get("engine_samples", []):
            if sample["repetition"]:
                engine.setdefault((worker["provider"], worker["route"], sample["case"]), []).append(sample)
    rows = []
    for (provider, route, case), samples in sorted(series.items()):
        rows.append({"provider": provider, "scope": "hybrid" if case in HYBRID else "standalone",
                     "route": route, "case": case, **percentiles(s["wall_ms"] for s in samples),
                     "cpu_p50_ms": median(s["cpu_ms"] for s in samples)})
        key = (provider, route, case)
        if key in engine:
            timers = [s["engine_ms"] for s in engine[key]]
            if len(timers) != len(samples) or not all(math.isfinite(t) and t >= 0 for t in timers):
                raise ValueError(f"Invalid engine execution series for {key}")
            rows[-1]["engine_execution"] = percentiles(timers)
            if route.startswith("qw_"):
                rows[-1]["other_warm_work"] = percentiles(
                    (s["end_ns"] - s["start_ns"]) / 1e6 - s["engine_ms"] for s in engine[key])
    medians = {(r["provider"], r["route"], r["case"]): r["p50_ms"] for r in rows}
    for row in rows:
        route = row["route"]
        if row["scope"] == "standalone" and route.startswith("qw_"):
            row["qw_over_direct"] = row["p50_ms"] / medians[row["provider"], "direct_cypher", row["case"]]
            if (row["provider"], lookup.DIRECT_PREPARED, row["case"]) in medians:
                reference = (lookup.DIRECT_PREPARED if route == PREPARED_ROUTE else
                             lookup.NATIVE_REFERENCE.get(route, "direct_cypher"))
                row["matched_direct_route"] = reference
                row["qw_over_matched_direct"] = row["p50_ms"] / medians[row["provider"], reference, row["case"]]
    return rows


def release_metadata(a, common, binaries):
    source_commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", "--end-of-options", a.source_revision + "^{commit}"],
        cwd=a.source_checkout, text=True).strip()
    hashes = {**binaries, "extension": run.digest(a.extension)}
    if a.phase_extension:
        hashes["phase_extension"] = run.digest(a.phase_extension)
    return {**common, "workspace_head": source_commit, "binaries": hashes}


def verify_micro(a, report, providers, expected_rows):
    """Require SQLLogic query and snapshot checks before publishing a CM-LDBC record."""
    sys.path.insert(0, str(run.ROOT / "test" / "stabilization"))
    try:
        from run_sqllogictest import PIN_PROBE_SQL, run_cases
    finally:
        sys.path.pop(0)

    test_dir = Path(__file__).resolve().parent / "tracker"
    results_test = test_dir / "micro_results.test"
    snapshot_tests = [test_dir / name for name in ("micro_snapshot.test", "workload_snapshot.test")]
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
        run_cases(a.duckdb_unittest, scratch, {"QW_TRACKER_SNAPSHOT": snapshot}, snapshot_tests)
    return {"providers": providers, "checks": {test.name: run.digest(test) for test in (results_test, *snapshot_tests)}}


def benchmark(a):
    if a.hybrid:
        with TemporaryDirectory(prefix="qw-hybrid-") as directory:
            a.application_directory = Path(directory)
            benchmark_suite(a)
    else:
        benchmark_suite(a)


def benchmark_suite(a):
    supported_host = (platform.system(), platform.machine()) in {("Darwin", "arm64"), ("Linux", "aarch64")}
    if not supported_host or a.runs < 1 or a.blocks < 2 or a.blocks % 2 or a.timeout <= 0:
        raise ValueError("Use native ARM64 Linux or macOS, positive runs/worker timeout and an even number of blocks >= 2")
    is_micro = getattr(a, "micro", False)
    if a.fixture is None:
        a.fixture = run.BUILD / ("mod32" if is_micro or a.hybrid else "mod1")
    if a.hybrid:
        suite = APPLICATION_CASES
    elif is_micro:
        suite = MICRO_CASES
    else:
        suite = [name for name in CASES if name not in MICRO_CASES and name not in APPLICATION_CASES]
    if set(a.case or []) - set(suite):
        raise ValueError("Select application cases with --hybrid or CM-LDBC cases with --micro")
    cases = [name for name in suite if not a.case or name in a.case]
    providers = sorted(set(a.provider or run.ENGINES))
    if is_micro or a.hybrid:
        if a.session_lookups or a.include_prepared:
            raise ValueError("Hybrid suites exclude standalone lookup controls")
        if not a.describe:
            a.duckdb_unittest = a.duckdb_unittest.resolve(strict=True)
    if a.session_lookups:
        if set(a.provider or []) - {"ladybug"} or set(a.case or []) - lookup.KEYS.keys():
            raise ValueError("--session-lookups accepts Ladybug lookup and lookup_miss")
        providers = ["ladybug"]
        cases = [name for name in lookup.KEYS if not a.case or name in a.case]
    pairing = (a.baseline_extension, a.baseline_revision, a.baseline_out)
    supplied = [arg is not None for arg in pairing]
    if any(supplied) and not all(supplied):
        raise ValueError("Supply baseline extension, revision and output together")
    if a.baseline_phase_extension and not all(supplied):
        raise ValueError("A baseline diagnostic extension requires a paired baseline")
    if a.describe and (a.out or any(supplied)):
        raise ValueError("Use --describe alone to write the candidate workload description")
    fixture = json.loads((a.fixture / "fixture.json").read_text())
    verify_fixture(a.fixture, fixture)
    if is_micro:
        csv_path = a.fixture / "edges.csv"
        a.micro_relations, edge_count = micro.fixture_inputs(csv_path)
        rows = micro.expected_rows(micro.edge_rows(csv_path), a.micro_relations)
        expected = {name: run.signature(list(zip(*rows[name]))) for name in cases}
    elif a.hybrid:
        a.application_parameters, rows = {}, {}
        csv_path = a.fixture / "edges.csv"
        for name in cases:
            directory = a.application_directory / name
            directory.mkdir()
            a.application_parameters[name], rows[name] = application.CASES[name].prepare(csv_path, directory)
        expected = {name: application.signature(rows[name]) for name in cases}
        edge_count = sum(1 for _ in micro.edge_rows(csv_path))
    else:
        oracle = run.oracle(a.fixture)
        expected = {CASES[n][1]: oracle["expected"][CASES[n][1]] for n in cases}
        edge_count = oracle["edges"]
    if "lookup_miss" in cases and expected["lookup_miss"][0] != 0:
        raise ValueError("lookup_miss requires -1 to be absent")
    routes = {k: [n for n in cases if n in group] for k, group in ROUTES.items()
              if k != PREPARED_ROUTE or a.include_prepared}
    if a.session_lookups:
        routes = {k: cases for k in ("direct_cypher", "qw_cypher", *lookup.CONTROLS)}
        if a.include_prepared:
            routes[PREPARED_ROUTE] = cases
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
              "statements": {n: CASES[n][0] for n in cases}, "watchlist": None if is_micro or a.hybrid else run.KEYS}
    if is_micro:
        common["micro"] = {"source_revision": micro.REVISION, "host_threshold": micro.HOST_THRESHOLD,
                           "relations": a.micro_relations, "providers": providers}
        common["micro_workloads_sha256"] = run.digest(Path(micro.__file__))
    if a.hybrid:
        common["application"] = {"providers": providers, "parameters": a.application_parameters,
                                 "routes": [route for route, names in routes.items() if names]}
    if is_micro or a.hybrid:
        a.micro_cases = workload_manifest.load_manifest()
        common["workload_evidence"] = {
            name: workload_manifest.workload_evidence(
                a.micro_cases[name], scale=f"mod{fixture['modulus']}",
                fixture_sha256=fixture["files"]["edges.csv"]["sha256"],
                sql=common["statements"][name],
                parameters=a.application_parameters[name] if a.hybrid else a.micro_relations,
                oracle_rows=expected[name][0], oracle_sha256=expected[name][1])
            for name in cases
        }
        common["workload_schedule"] = replay_schedule(providers, routes, a.blocks, a.runs)
        common["schedule_sha256"] = workload_manifest.canonical_sha256(common["workload_schedule"])
    if routes.get(PREPARED_ROUTE):
        common["prepared_statements"] = {name: prepared_sql(name) for name in routes[PREPARED_ROUTE]}
    if a.session_lookups:
        common["session_lookups"] = {
            "version": 1, "graph": run.GRAPH_ALIAS, "dialect": "cypher",
            "person_ids": {name: lookup.KEYS[name] for name in cases},
            "statements": {route: {name: prepared_sql(name) if route == PREPARED_ROUTE else
                                   lookup.statement(route, STANDALONE[name][0]) for name in cases} for route in routes},
        }
        common["session_lookups_sha256"] = run.digest(Path(lookup.__file__))
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
        baseline.phase_extension = a.baseline_phase_extension
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
        report["bootstrap_summary"] = summarize_bootstrap(report["workers"])
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        if is_micro or a.hybrid:
            if run.digest(release.extension) != report["binaries"]["extension"]:
                raise ValueError("QuackWeave extension changed during measurement")
            if a.hybrid:
                report["application_sqllogic"] = application.verify(release, report, rows, run, a.application_directory)
            else:
                report["micro_sqllogic"] = verify_micro(release, report, providers, rows)
            if run.digest(release.extension) != report["binaries"]["extension"]:
                raise ValueError("QuackWeave extension changed during SQLLogic verification")
    if is_micro or a.hybrid:
        verify_fixture(a.fixture, fixture)
        if run.digest(a.library) != binaries["duckdb_library"]:
            raise ValueError("DuckDB library changed during measurement")
    with ExitStack() as rollback:
        for _, path, report in subjects:
            publish(path, report)
            rollback.callback(path.unlink)
        rollback.pop_all()
    for _, path, report in subjects:
        print_summary(path, report)


def print_summary(path, report):
    print(path)
    print("Warm provider engine execution (ms, native query summary)")
    print("provider\troute\tcase\tn\tp50_ms\tp95_ms\tother_warm_work_p50_ms")
    for row in report["summary"]:
        if engine := row.get("engine_execution"):
            other = row.get("other_warm_work")
            print(row["provider"], row["route"], row["case"], engine["n"], f"{engine['p50_ms']:.3f}",
                  f"{engine['p95_ms']:.3f}", f"{other['p50_ms']:.3f}" if other else "—", sep="\t")
    print("One-time connection bootstrap (ms)")
    print("provider\troute\tconnections\tp50_ms\tp95_ms")
    for row in report["bootstrap_summary"]:
        print(row["provider"], row["route"], row["n"], f"{row['p50_ms']:.3f}", f"{row['p95_ms']:.3f}", sep="\t")
    print("Warm client latency through Arrow fetch (ms)")
    session = "session_lookups" in report
    print("provider\troute\tcase\tn\tp50_ms\tp95_ms\tqw_over_direct" +
          ("\tmatched_direct_route\tqw_over_matched_direct" if session else ""))
    for row in report["summary"]:
        ratio = f"{row['qw_over_direct']:.2f}x" if "qw_over_direct" in row else "—"
        fields = [row["provider"], row["route"], row["case"], row["n"],
                  f"{row['p50_ms']:.3f}", f"{row['p95_ms']:.3f}", ratio]
        if session:
            matched = row.get("qw_over_matched_direct")
            fields.extend([row.get("matched_direct_route", "—"), f"{matched:.2f}x" if matched is not None else "—"])
        print(*fields, sep="\t")
    if "micro" in report or "application" in report:
        crossings = {}
        for worker in report["workers"]:
            for case, rows in worker["graph_scan_rows"].items():
                crossings.setdefault((worker["provider"], worker["route"], case), set()).add(rows)
        print("Hybrid provider rows delivered to DuckDB")
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
    if before.get("session_lookups") != after.get("session_lookups"):
        raise ValueError("Incompatible snapshots: session lookup workloads differ")
    if before.get("micro") != after.get("micro"):
        raise ValueError("Incompatible snapshots: CM-LDBC inputs differ")
    if before.get("application") != after.get("application"):
        raise ValueError("Incompatible snapshots: application inputs differ")
    if "application" in before and (not before.get("application_sqllogic")
                                    or before["application_sqllogic"] != after.get("application_sqllogic")):
        raise ValueError("Incompatible snapshots: application SQLLogic receipts differ")
    sys.path.insert(0, str(Path(__file__).resolve().parent / "tracker"))
    try:
        from ci import verify_workload_replay
    finally:
        sys.path.pop(0)
    if verify_workload_replay(before) != verify_workload_replay(after):
        raise ValueError("Incompatible snapshots: workload evidence or replay schedule differs")
    if before["id"] == after["id"]:
        raise ValueError("Select two distinct benchmark runs")
    def by_key(report):
        return {(r["provider"], r["route"], r["case"]): r for r in report["summary"]}
    baseline = by_key(before)
    candidate = by_key(after)
    if baseline.keys() != candidate.keys() or before["statements"] != after["statements"] or before["expected"] != after["expected"]:
        raise ValueError("Incompatible snapshots: workload matrix, statement or oracle differs")
    print(f"{before['id']} -> {after['id']}")
    print("Warm provider engine execution (ms)")
    print("provider\troute\tcase\told_p50_ms\tnew_p50_ms\told_p95_ms\tnew_p95_ms")
    for key, row in candidate.items():
        old_engine, new_engine = baseline[key].get("engine_execution"), row.get("engine_execution")
        if old_engine and new_engine:
            print(*key, *(f"{group[k]:.3f}" for k in ("p50_ms", "p95_ms") for group in (old_engine, new_engine)), sep="\t")
    if before.get("bootstrap_summary") and after.get("bootstrap_summary"):
        print("One-time connection bootstrap (ms)")
        print("provider\troute\told_p50_ms\tnew_p50_ms\told_p95_ms\tnew_p95_ms")
        old_boot = {(r["provider"], r["route"]): r for r in before["bootstrap_summary"]}
        for row in after["bootstrap_summary"]:
            key = (row["provider"], row["route"])
            print(*key, *(f"{group[k]:.3f}" for k in ("p50_ms", "p95_ms") for group in (old_boot[key], row)), sep="\t")
    print("Warm client latency through fetch (ms)")
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
    measure.add_argument("--phase-extension", type=Path, help="Matching diagnostic release for engine timings through bare Cypher/GQL")
    measure.add_argument("--baseline-phase-extension", type=Path, help="Matching diagnostic release for the paired baseline")
    measure.add_argument("--case", action="append", choices=CASES)
    suite = measure.add_mutually_exclusive_group()
    suite.add_argument("--micro", action="store_true", help="Measure the CM-LDBC hybrid workload suite")
    suite.add_argument("--hybrid", action="store_true", help="Measure the application Hybrid Query workloads")
    measure.add_argument("--duckdb-unittest", type=Path,
                         default=Path(os.environ.get("DUCKDB_UNITTEST", run.ROOT / "build/benchmark-host/unittest")),
                         help="Pinned SQLLogic runner for the Hybrid workload and snapshot gates")
    measure.add_argument("--include-prepared", action="store_true",
                         help="Also time reused explicit-schema qw_query Cypher statements")
    measure.add_argument("--session-lookups", action="store_true",
                         help="Measure Ladybug hits and misses on a stable session with matched preparation controls")
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
    worker.add_argument("--route", required=True, choices=[*ROUTES, *lookup.CONTROLS])
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
