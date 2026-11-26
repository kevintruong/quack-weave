#!/usr/bin/env python3
"""Exercise the QuackWeave typed Cypher SQL surface against pinned native binaries."""

import argparse
import csv
import io
import json
from pathlib import Path
import re
import subprocess
import tempfile


DUCKDB_VERSION = "v2.0.1"
LADYBUG_VERSION = "0.22.3"
TRAVERSAL = (
    "MATCH (src:Document {id: 100})-[:LINKS_TO]->(dst:Document) "
    "RETURN dst.id AS document_id"
)
VECTOR_FIXTURE_ROWS = 5_001
FIXTURE = f"""\
CREATE NODE TABLE Document(id INT64 PRIMARY KEY, title STRING, active BOOL, ratio DOUBLE);
CREATE REL TABLE LINKS_TO(FROM Document TO Document);
CREATE NODE TABLE VectorRow(id INT64 PRIMARY KEY);
CREATE (d:Document {{id: 100, title: 'Source', active: false, ratio: 0.0}});
CREATE (d:Document {{id: 101, title: 'Linked, λ', active: true, ratio: 1.25}});
CREATE (d:Document {{id: 102}});
MATCH (src:Document {{id: 100}}), (dst:Document {{id: 101}}) CREATE (src)-[:LINKS_TO]->(dst);
MATCH (src:Document {{id: 101}}), (dst:Document {{id: 102}}) CREATE (src)-[:LINKS_TO]->(dst);
UNWIND range(1, {VECTOR_FIXTURE_ROWS}) AS id CREATE (:VectorRow {{id: id}});
"""


def sql_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def graph_query(cypher, schema="document_id BIGINT", *, alias="kg", dialect="cypher"):
    return (
        f"qw_query({sql_literal(alias)}, {sql_literal(dialect)}, "
        f"{sql_literal(cypher)}, schema := {sql_literal(schema)})"
    )


def provision(graph, alias="kg", *, max_batch_bytes=None, timeout_ms=None):
    config = {"alias": alias, "path": str(graph)}
    if max_batch_bytes is not None:
        config["max_batch_bytes"] = max_batch_bytes
    if timeout_ms is not None:
        config["timeout_ms"] = timeout_ms
    return f"SET GLOBAL qw_ladybug_config = {sql_literal(json.dumps(config))};\n"


def duckdb(binary, sql, *, bail=True):
    args = [binary, "-no-agent", "-unsigned", "-batch", "-csv", "-noheader"]
    if bail:
        args.append("-bail")
    return subprocess.run(
        [*args, ":memory:"],
        input=sql,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def read_rows(result):
    if result.returncode:
        raise AssertionError(result.stderr.strip() or result.stdout.strip())
    return list(csv.reader(io.StringIO(result.stdout)))


def expect_rows(result, wanted):
    rows = read_rows(result)
    if rows != wanted:
        raise AssertionError(f"Expected {wanted!r}, received {rows!r}")


def ladybug(binary, graph, cypher, *, read_only=False):
    args = [binary, "-m", "jsonlines", "-s", "-b", "-p", graph.parent]
    if read_only:
        args.append("-r")
    result = subprocess.run(
        [*args, graph], input=cypher, text=True, capture_output=True, timeout=30, check=False
    )
    if result.returncode or re.search(r"\b(?:Exception|Error):", result.stdout + result.stderr):
        raise AssertionError(f"Ladybug fixture error:\n{result.stderr}{result.stdout}")
    return [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]


def snapshot_graph(lbug, graph):
    return ladybug(
        lbug,
        graph,
        "MATCH (d:Document) RETURN d.id AS id, d.title AS title, "
        "d.active AS active, d.ratio AS ratio ORDER BY id;\n"
        "MATCH (a:Document)-[:LINKS_TO]->(b:Document) RETURN a.id AS src, b.id AS dst ORDER BY src, dst;\n"
        "CALL show_tables() RETURN name AS table_name ORDER BY table_name;\n",
        read_only=True,
    )


def expect_failure(result, diagnostic):
    if result.returncode != 1 or "Error:" not in result.stderr or diagnostic not in result.stderr:
        raise AssertionError(
            f"Expected {diagnostic}, received exit {result.returncode}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )


def run_cases(duckdb_binary, lbug, extension, graph):
    load = f"LOAD {sql_literal(extension.resolve(strict=True))};\n"
    setup = load + provision(graph)
    select = f"SELECT * FROM {graph_query(TRAVERSAL)};\n"

    expect_rows(duckdb(duckdb_binary, setup + select), [["101"]])
    expect_rows(
        duckdb(duckdb_binary, load + "SELECT provider_id FROM qw_graph_providers() ORDER BY 1;\n"),
        [["ladybug"], ["neo4j"], ["relate"]],
    )
    expect_rows(
        duckdb(duckdb_binary, setup + """
            SELECT document_id
            FROM GRAPH_TABLE (
                kg MATCH (src:Document)-[edge:LINKS_TO]->(dst:Document)
                WHERE src.id = 100
                COLUMNS (dst.id AS document_id)
            );
        """),
        [["101"]],
    )
    print("PASS all_providers_and_graph_table")
    print("PASS normal_graph_read")
    multi_hop = graph_query(
        "MATCH (src:Document {id: 100})-[:LINKS_TO*1..2]->(dst:Document) "
        "RETURN dst.id AS document_id"
    )
    expect_rows(
        duckdb(duckdb_binary, setup + f"SELECT * FROM {multi_hop} ORDER BY document_id;\n"),
        [["101"], ["102"]],
    )
    expect_rows(
        duckdb(
            duckdb_binary,
            setup
            + f"SELECT wanted.title FROM {graph_query(TRAVERSAL)} AS graph "
            "JOIN (VALUES (101, 'DuckDB side'), (102, 'Unlinked')) AS wanted(id,title) "
            "ON wanted.id = graph.document_id;\n",
        ),
        [["DuckDB side"]],
    )
    expect_rows(
        duckdb(
            duckdb_binary,
            setup + "SELECT coalesce(wanted.id::VARCHAR, '<null>'), count(graph.document_id) "
            "FROM (VALUES (101::BIGINT), (101), (102), (NULL)) AS wanted(id) "
            f"LEFT JOIN {graph_query(TRAVERSAL)} AS graph ON wanted.id = graph.document_id "
            "GROUP BY wanted.id ORDER BY wanted.id NULLS LAST;\n",
        ),
        [["101", "2"], ["102", "0"], ["<null>", "0"]],
    )
    scalar_query = graph_query(
        "MATCH (d:Document) RETURN d.id AS id, d.title AS title, d.active AS active, d.ratio AS ratio",
        "id BIGINT, title VARCHAR, active BOOLEAN, ratio DOUBLE",
        alias="KG",
        dialect="CyPhEr",
    )
    expect_rows(
        duckdb(
            duckdb_binary,
            setup
            + "SELECT id, coalesce(title, '<null>'), coalesce(active::VARCHAR, '<null>'), "
            f"coalesce(ratio::VARCHAR, '<null>'), typeof(id), typeof(title), typeof(active), typeof(ratio) "
            f"FROM {scalar_query} WHERE id >= 101 ORDER BY id;\n",
        ),
        [
            ["101", "Linked, λ", "true", "1.25", "BIGINT", "VARCHAR", "BOOLEAN", "DOUBLE"],
            ["102", "<null>", "<null>", "<null>", "BIGINT", "VARCHAR", "BOOLEAN", "DOUBLE"],
        ],
    )
    empty = graph_query("MATCH (d:Document) WHERE d.id = 0 RETURN d.id AS document_id")
    expect_rows(duckdb(duckdb_binary, setup + f"SELECT count(*) FROM {empty};\n"), [["0"]])
    vector = graph_query("MATCH (v:VectorRow) RETURN v.id AS id", "id BIGINT")
    expected_ids = range(1, VECTOR_FIXTURE_ROWS + 1)
    expect_rows(
        duckdb(duckdb_binary, setup + f"SELECT count(*), sum(id), min(id), max(id) FROM {vector};\n"),
        [[str(len(expected_ids)), str(sum(expected_ids)), "1", str(VECTOR_FIXTURE_ROWS)]],
    )
    semicolon = graph_query(
        "MATCH (d:Document {id: 100}) RETURN 'semi;colon' AS title", "title VARCHAR"
    )
    expect_rows(duckdb(duckdb_binary, setup + f"SELECT * FROM {semicolon};\n"), [["semi;colon"]])
    expect_rows(
        duckdb(duckdb_binary, setup + f"SELECT 42 FROM {vector} LIMIT 1;\n" + select),
        [["42"], ["101"]],
    )
    print("PASS join_scalar_empty_multibatch_and_limit")

    bad_cypher = graph_query("this has no valid Cypher statement")
    read_rows(duckdb(duckdb_binary, setup + f"EXPLAIN SELECT * FROM {bad_cypher};\n"))
    read_rows(duckdb(duckdb_binary, setup + f"PREPARE read_graph AS SELECT * FROM {bad_cypher};\n"))
    expect_failure(
        duckdb(duckdb_binary, setup + f"EXPLAIN ANALYZE SELECT * FROM {bad_cypher};\n"),
        "QW_ADMISSION",
    )
    expect_failure(duckdb(duckdb_binary, setup + f"SELECT * FROM {bad_cypher};\n"), "QW_ADMISSION")
    for invalid, diagnostic in (
        (graph_query(TRAVERSAL, "wrong_name BIGINT"), "QW_SCHEMA"),
        (graph_query(TRAVERSAL, "document_id DOUBLE"), "QW_SCHEMA"),
        (graph_query(TRAVERSAL, "d BIGINT, D BIGINT"), "QW_ARGUMENT"),
        (graph_query(TRAVERSAL, ""), "QW_ARGUMENT"),
        (graph_query(TRAVERSAL, alias="unknown"), "QW_CONFIG"),
        (graph_query(TRAVERSAL, dialect="sql"), "QW_ARGUMENT"),
    ):
        expect_failure(duckdb(duckdb_binary, setup + f"SELECT * FROM {invalid};\n"), diagnostic)
    expect_failure(duckdb(duckdb_binary, load + select), "QW_CONFIG")
    expect_failure(duckdb(duckdb_binary, setup + "RESET qw_ladybug_config;\n" + select), "QW_CONFIG")
    expect_failure(
        duckdb(
            duckdb_binary,
            setup + f"PREPARE old_config AS {select}" + provision(graph, alias="reconfigured")
            + "EXECUTE old_config;\n",
        ),
        "QW_CONFIG",
    )
    expect_failure(
        duckdb(duckdb_binary, setup + "SET enable_external_access = false;\n" + select),
        "QW_ACCESS",
    )
    invalid_graph = graph.parent / "invalid.lbdb"
    invalid_graph.write_bytes(b"not the contents of a Ladybug database")
    invalid_setup = load + provision(invalid_graph)
    read_rows(duckdb(duckdb_binary, invalid_setup + "EXPLAIN " + select))
    expect_failure(duckdb(duckdb_binary, invalid_setup + select), "QW_OPEN")
    print("PASS binding_schema_explain_and_host_policy")

    expected = snapshot_graph(lbug, graph)
    if expected != [
        {"id": 100, "title": "Source", "active": False, "ratio": 0.0},
        {"id": 101, "title": "Linked, λ", "active": True, "ratio": 1.25},
        {"id": 102, "title": None, "active": None, "ratio": None},
        {"src": 100, "dst": 101},
        {"src": 101, "dst": 102},
        {"table_name": "Document"},
        {"table_name": "LINKS_TO"},
        {"table_name": "VectorRow"},
    ]:
        raise AssertionError(f"Unexpected Ladybug fixture snapshot: {expected!r}")

    def reject_product_query(cypher):
        expect_failure(
            duckdb(duckdb_binary, setup + f"SELECT * FROM {graph_query(cypher)};\n"),
            "QW_ADMISSION",
        )
        if snapshot_graph(lbug, graph) != expected:
            raise AssertionError("Ladybug data or schema changed after the rejected query")

    mutation = "CREATE (d:Document {id: 999, title: 'Unexpected'}) RETURN d.id AS document_id"
    reject_product_query(mutation)
    print("PASS write_rejected_graph_unchanged")
    reject_product_query(f"{TRAVERSAL}; {mutation}")
    print("PASS batch_rejected_graph_unchanged")
    reject_product_query(f"{TRAVERSAL}; {TRAVERSAL}")
    reject_product_query(
        "MATCH (d:Document {id: 100}) SET d.title = 'Unexpected' RETURN d.id AS document_id"
    )
    reject_product_query("MATCH (d:Document {id: 102}) DETACH DELETE d")
    reject_product_query("CREATE NODE TABLE Unexpected(id INT64 PRIMARY KEY)")
    # Use the actual administrative result type so schema checking cannot mask admission.
    admin = graph_query("CALL show_tables() RETURN name AS table_name", "table_name VARCHAR")
    expect_failure(duckdb(duckdb_binary, setup + f"SELECT * FROM {admin};\n"), "QW_ADMISSION")
    output_path = graph.parent / "unexpected-export.csv"
    reject_product_query(f"COPY ({TRAVERSAL}) TO {sql_literal(output_path)}")
    if output_path.exists():
        raise AssertionError("Rejected Cypher unexpectedly created an export file")
    print("PASS schema_write_update_and_administration_rejected")

    tiny_budget = load + provision(graph, max_batch_bytes=1)
    truncated = duckdb(duckdb_binary, tiny_budget + select)
    expect_failure(truncated, "QW_BATCH_BUDGET")
    if truncated.stdout:
        raise AssertionError("An over-budget batch produced rows before rejection")
    expect_rows(
        duckdb(duckdb_binary, tiny_budget + "RESET qw_ladybug_config;\n" + provision(graph) + select),
        [["101"]],
    )
    print("PASS batch_budget_rejects_before_output_and_reset_recovers")

    product = graph_query(
        "MATCH (a:VectorRow), (b:VectorRow) RETURN sum(a.id * b.id) AS product", "product BIGINT"
    )
    deadline_setup = load + provision(graph, timeout_ms=1)
    timed_out = duckdb(duckdb_binary, deadline_setup + f"SELECT * FROM {product};\n")
    expect_failure(timed_out, "QW_TIMEOUT")
    if timed_out.stdout:
        raise AssertionError("A timed-out scan produced rows before rejection")
    recovered = duckdb(
        duckdb_binary,
        deadline_setup + f"SELECT * FROM {product};\n" + provision(graph) + select,
        bail=False,
    )
    expect_failure(recovered, "QW_TIMEOUT")
    if list(csv.reader(io.StringIO(recovered.stdout))) != [["101"]]:
        raise AssertionError("The same connection could not open a normal scan after timeout")
    print("PASS timeout_rejects_before_output_and_next_scan_recovers")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duckdb", default="duckdb")
    parser.add_argument("--extension", type=Path)
    parser.add_argument("--lbug", default="lbug")
    options = parser.parse_args()
    version = subprocess.run(
        [options.duckdb, "-no-agent", "-version"],
        text=True,
        capture_output=True,
        timeout=30,
        check=True,
    ).stdout.split()
    if not version or version[0] != DUCKDB_VERSION:
        parser.error(f"DuckDB {DUCKDB_VERSION} is required")

    if not options.extension:
        # Without an artifact, the same read exposes the missing feature on the host baseline.
        expect_rows(duckdb(options.duckdb, f"SELECT * FROM {graph_query(TRAVERSAL)};\n"), [["101"]])
        return

    lbug_version = subprocess.run(
        [options.lbug, "-v"], text=True, capture_output=True, timeout=30, check=True
    )
    version_pattern = rf"(?<![\d.]){re.escape(LADYBUG_VERSION)}(?![\d.])"
    if not re.search(version_pattern, lbug_version.stdout + lbug_version.stderr):
        parser.error(f"Ladybug {LADYBUG_VERSION} is required")
    with tempfile.TemporaryDirectory(prefix="quack-weave-cypher-") as root:
        graph = Path(root).resolve() / "documents.lbdb"
        ladybug(options.lbug, graph, FIXTURE)
        if not graph.is_file():
            raise AssertionError("Ladybug did not create the graph database file")
        run_cases(options.duckdb, options.lbug, options.extension, graph)


if __name__ == "__main__":
    main()
