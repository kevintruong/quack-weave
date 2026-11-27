"""Ordered Hybrid Query workloads with shared benchmark and SQLLogic execution."""
from hashlib import sha256
import json
from pathlib import Path

import directory_join_topk
import prepared_watchlist_churn


CASES = {case.CASE_ID: case for case in (directory_join_topk, prepared_watchlist_churn)}
HOST_ROUTE = "qw_pgq_host"
SLT = {"BIGINT": "I", "VARCHAR": "T"}


def statements():
    return {name: case.SQL for name, case in CASES.items()}


def signature(rows):
    from workload_manifest import canonical_sha256

    return [len(rows), canonical_sha256(rows)]


def setup_sql(case, parameters, directory, prefilter):
    return [f"SET SESSION qw_enable_runtime_watchlist = {'true' if prefilter else 'false'}",
            *case.setup_sql(parameters, directory)]


def query_steps(case, parameters, expected):
    if hasattr(case, "operations"):
        for epoch, (commands, query) in zip(parameters["epochs"], case.operations(parameters), strict=True):
            rows = [row[1:] for row in expected if row[0] == epoch["epoch"]]
            yield commands, query, case.SCHEMA[1:], rows
    else:
        yield [], case.SQL, case.SCHEMA, expected


def verify(a, report, rows, run, scratch):
    """Replay the measured SQL against independent exact rows through pinned DuckDB SQLLogic."""
    import sys

    sys.path.insert(0, str(run.ROOT / "test" / "stabilization"))
    try:
        from run_sqllogictest import PIN_PROBE_SQL, run_cases
    finally:
        sys.path.pop(0)

    snapshot = scratch / "snapshot.json"
    snapshot.write_text(json.dumps(report, sort_keys=True, allow_nan=False), encoding="utf-8")
    snapshot_test = Path(__file__).with_name("tracker") / "workload_snapshot.test"
    variables = {"QW_APPLICATION_EXTENSION": run.sql_literal(a.extension.resolve())}
    run_cases(a.duckdb_unittest, scratch, {}, stdin=PIN_PROBE_SQL)

    for worker in report["workload_schedule"]:
        provider, route = worker["provider"], worker["route"]
        if worker["block"] != 0:
            continue
        graph = (a.fixture / run.ENGINES[provider]).resolve()
        variables["QW_APPLICATION_REGISTER"] = f"SET GLOBAL qw_{provider}_config = " + run.sql_literal(
            json.dumps({"alias": run.GRAPH_ALIAS, "path": str(graph)}))
        test = scratch / f"{provider}-{route}.test"
        blocks = [
            "require parquet",
            "test-env QW_APPLICATION_EXTENSION UNSET_QW_APPLICATION_EXTENSION",
            "test-env QW_APPLICATION_REGISTER UNSET_QW_APPLICATION_REGISTER",
            "statement ok\nLOAD {QW_APPLICATION_EXTENSION};",
            "statement ok\n{QW_APPLICATION_REGISTER};",
            "statement ok\nSET threads = 1;",
            "statement ok\nSET SESSION qw_graph_dialect = 'gql';",
        ]
        for name in dict.fromkeys(sample["case"] for sample in worker["sequence"]):
            case = CASES[name]
            parameters = a.application_parameters[name]
            directory = a.application_directory / name
            blocks.extend(f"statement ok\n{sql.rstrip(';')};"
                          for sql in setup_sql(case, parameters, directory, route != HOST_ROUTE))
            for commands, query, schema, expected in query_steps(case, parameters, rows[name]):
                blocks.extend(f"statement ok\n{sql.rstrip(';')};" for sql in commands)
                columns = "".join(SLT[kind] for _, kind in schema)
                answer = "\n".join("\t".join("NULL" if value is None else str(value) for value in row)
                                   for row in expected)
                blocks.append(f"query {columns} nosort\n{query};\n----\n{answer}")
        test.write_text("\n\n".join(blocks) + "\n\n", encoding="utf-8")
        run_cases(a.duckdb_unittest, scratch, variables, [test])

    run_cases(a.duckdb_unittest, scratch, {"QW_TRACKER_SNAPSHOT": snapshot}, [snapshot_test])
    # Paths inside generated SQLLogic tests vary per run; bind stable inputs and exact rows.
    receipt = json.dumps(report["workload_evidence"], sort_keys=True, separators=(",", ":")).encode()
    return {"checks": {snapshot_test.name: run.digest(snapshot_test),
                       "scaled_queries": sha256(receipt).hexdigest()}}
