#!/usr/bin/env python3
"""Validate packaged Cypher/GQL parity with the pinned DuckDB and Ladybug CLIs."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from mvp1_acceptance import (
    DUCKDB_VERSION, FIXTURE, LADYBUG_VERSION, VECTOR_FIXTURE_ROWS, duckdb, expect_failure, expect_rows,
    graph_query, ladybug, provision, read_rows, snapshot_graph, sql_literal,
)


PATTERN = "MATCH (a:Document)-[:LINKS_TO]->(b:Document)"
PROJECTION = "RETURN b.id AS document_id, b.title AS title"
SCHEMA = "document_id BIGINT, title VARCHAR"
PARITY_FIXTURE = FIXTURE + """
CREATE (d:Document {id: 103, title: "O'Brien; λ"});
MATCH (a:Document {id: 100}), (b:Document {id: 101}) CREATE (a)-[:LINKS_TO]->(b);
MATCH (a:Document {id: 101}), (b:Document {id: 103}) CREATE (a)-[:LINKS_TO]->(b);
CREATE REL TABLE HAS_SAMPLE(FROM Document TO VectorRow);
MATCH (a:Document {id: 100}), (sample:VectorRow) CREATE (a)-[:HAS_SAMPLE]->(sample);
"""


def query(predicate, *, keyword="WHERE"):
    return f"{PATTERN} {keyword} {predicate} {PROJECTION}"


def scan(text, dialect="gql", schema=SCHEMA):
    return graph_query(text, schema, dialect=dialect)


def load(extension):
    return f"LOAD {sql_literal(extension.resolve(strict=True))};\n"


def check_relocation(binary, extension, graph):
    moved = graph.parent / "relocated package" / extension.name
    moved.parent.mkdir()
    shutil.copy2(extension, moved)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DYLD_", "LD_"))}
    text = query("a.id = 100")
    sql = load(moved) + provision(graph)
    for dialect in ("cypher", "gql"):
        sql += f"SELECT document_id FROM {scan(text, dialect)} ORDER BY document_id;\n"
    sql += """\
SELECT count(*) FROM duckdb_extensions()
WHERE loaded AND extension_name IN ('gql', 'duckgql', 'duckdb_gql');
"""
    run = subprocess.run(
        [binary, "-no-init", "-no-agent", "-unsigned", "-batch", "-csv", "-noheader", "-bail", ":memory:"],
        input=sql, text=True, capture_output=True, timeout=30, check=False,
        env=env, cwd=moved.parent,
    )
    expect_rows(run, [["101"], ["101"], ["101"], ["101"], ["0"]])
    print("PASS relocated_artifact_loads_both_dialects")


def check_rows_and_cleanup(binary, extension, graph):
    setup = load(extension) + provision(graph)
    cases = [
        (query("a.id = 100"), query("a.id = 100"),
         [["101", "Linked, λ", "BIGINT", "VARCHAR"], ["101", "Linked, λ", "BIGINT", "VARCHAR"]]),
        (query("a.id = 101"), query("a.id = 101"),
         [["102", "<null>", "BIGINT", "VARCHAR"], ["103", "O'Brien; λ", "BIGINT", "VARCHAR"]]),
        (query("a.id = -1"), query("a.id = -1"), []),
        (query('b.title = "O\'Brien; λ"'), query('b.title = "O\'Brien; λ"', keyword="FILTER"),
         [["103", "O'Brien; λ", "BIGINT", "VARCHAR"]]),
    ]
    for cypher_text, gql_text, expected in cases:
        for dialect, text in (("cypher", cypher_text), ("gql", gql_text)):
            sql = (
                "SELECT document_id, coalesce(title, '<null>'), typeof(document_id), typeof(title) "
                f"FROM {scan(text, dialect)} ORDER BY document_id, title;\n"
            )
            expect_rows(duckdb(binary, setup + sql), expected)

    cypher = scan(query("a.id = 100"), "cypher")
    gql = scan(query("a.id = 100"))
    for call in (cypher, gql):
        sql = (
            f"SELECT d.title, count(*) FROM {call} AS g "
            "JOIN (VALUES (101, 'Found'), (102, 'Other')) AS d(id, title) ON d.id = g.document_id "
            "GROUP BY d.title;\n"
        )
        expect_rows(duckdb(binary, setup + sql), [["Found", "2"]])
    samples = scan(
        "MATCH (a:Document)-[:HAS_SAMPLE]->(sample:VectorRow) WHERE a.id = 100 RETURN sample.id AS id",
        schema="id BIGINT",
    )
    expect_rows(duckdb(binary, setup + f"SELECT count(*) FROM {samples};\n"), [[str(VECTOR_FIXTURE_ROWS)]])
    expect_rows(
        duckdb(binary, setup + f"SELECT 42 FROM {samples} LIMIT 1;\n"
               f"SELECT document_id FROM {cypher} ORDER BY document_id;\n"),
        [["42"], ["101"], ["101"]],
    )
    print("PASS typed_duplicate_nullable_empty_join_literal_and_early_close_parity")


def check_failures_and_explain(binary, lbug, extension, graph):
    setup = load(extension) + provision(graph)
    selected = f"SELECT * FROM {scan(query('a.id = 100'))};\n"
    invalid_graph = graph.parent / "invalid.lbdb"
    invalid_graph.write_bytes(b"not a Ladybug graph")
    invalid_setup = load(extension) + provision(invalid_graph)
    read_rows(duckdb(binary, invalid_setup + "PREPARE graph_read AS " + selected))
    if not read_rows(duckdb(binary, invalid_setup + "EXPLAIN " + selected)):
        raise AssertionError("Plain EXPLAIN did not produce a plan")
    expect_failure(duckdb(binary, invalid_setup + "EXPLAIN ANALYZE " + selected), "QW_OPEN")
    if not read_rows(duckdb(binary, setup + "EXPLAIN ANALYZE " + selected)):
        raise AssertionError("EXPLAIN ANALYZE did not return an executed plan")

    original = snapshot_graph(lbug, graph)
    negative = [
        (f"EXPLAIN SELECT * FROM {scan('MATCH (a:Document RETURN a.id AS document_id')};\n", "QW_GQL_PARSE"),
        (f"SELECT * FROM {scan('INSERT (:Document)')};\n", "QW_GQL_SUBSET"),
        (f"SELECT * FROM {scan(query('a.id = 100') + '; INSERT (:Document)')};\n", "QW_GQL_PARSE"),
        (f"SELECT * FROM {scan('OPTIONAL ' + query('a.id = 100'))};\n", "QW_GQL_SUBSET"),
        (f"SELECT * FROM {scan(query('a.id = 100'), schema='other_id BIGINT, title VARCHAR')};\n", "QW_SCHEMA"),
        (f"SELECT * FROM {scan(query('a.id = 100'), schema='document_id DOUBLE, title VARCHAR')};\n", "QW_SCHEMA"),
    ]
    for sql, diagnostic in negative:
        result = duckdb(binary, setup + sql)
        expect_failure(result, diagnostic)
        if result.stdout:
            raise AssertionError(f"{diagnostic} published rows before rejection")
    if snapshot_graph(lbug, graph) != original:
        raise AssertionError("Rejecting GQL changed the graph")
    print("PASS explain_bind_scan_and_rejection_preserve_graph")


def check_package_metadata_and_notices(extension):
    with extension.open("rb") as package:
        package.seek(-512, os.SEEK_END)
        metadata = package.read(256)
    version = metadata[4 * 32 : 5 * 32].rstrip(b"\0")
    if version != b"v0.2.0":
        raise AssertionError(f"Expected MVP2 footer version v0.2.0, received {version!r}")
    notices = extension.resolve().parent / "licenses"
    for name in ("DuckGQL-LICENSE", "openGQL-LICENSE", "ANTLR-LICENSE.txt"):
        license_file = notices / name
        if not license_file.is_file() or not license_file.read_bytes():
            raise AssertionError(f"Missing third-party notice {license_file}")
    print("PASS mvp2_footer_and_third_party_notices_shipped")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duckdb", required=True)
    parser.add_argument("--lbug", required=True)
    parser.add_argument("--extension", required=True, type=Path)
    args = parser.parse_args()
    binary = shutil.which(args.duckdb)
    if not binary:
        parser.error("DuckDB CLI was not found")
    binary = str(Path(binary).resolve())
    expect_rows(duckdb(binary, "SELECT version();\n"), [[DUCKDB_VERSION]])
    version = subprocess.check_output([args.lbug, "-v"], text=True, timeout=30).split()
    if not version or version[-1] != LADYBUG_VERSION:
        parser.error(f"Ladybug {LADYBUG_VERSION} is required")

    with tempfile.TemporaryDirectory(prefix="quack-weave-mvp2-") as root:
        graph = Path(root).resolve() / "documents.lbdb"
        ladybug(args.lbug, graph, PARITY_FIXTURE)
        check_relocation(binary, args.extension, graph)
        check_rows_and_cleanup(binary, args.extension, graph)
        check_failures_and_explain(binary, args.lbug, args.extension, graph)
        check_package_metadata_and_notices(args.extension)


if __name__ == "__main__":
    main()
