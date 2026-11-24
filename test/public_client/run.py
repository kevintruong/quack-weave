#!/usr/bin/env python3
"""Exercise the public graph statement and consume its typed result through DuckDB's ADBC driver."""

import argparse
from pathlib import Path
import sys
import tempfile

from adbc_driver_manager import dbapi


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "stabilization"))
from run_sqllogictest import DUCKDB_PIN_SOURCE, DUCKDB_PIN_VERSION, PIN_PROBE_SQL, run_cases
from mvp1_acceptance import ladybug, provision, sql_literal


ROUTES = """MATCH (origin:airport)-[route:route]->(destination:airport)
WHERE origin.code = 'ATL'
RETURN origin.code AS origin, destination.code AS destination, route.dist AS miles
LIMIT 10"""


def run(args, scratch):
    graph = scratch / "air_routes.lbdb"
    fixture = HERE.parent / "stabilization/fixtures/air_routes.cypher"
    ladybug(args.lbug, graph, fixture.read_text(encoding="utf-8"))
    destination = scratch / "client_results.duckdb"
    run_cases(args.duckdb_unittest, scratch, {}, stdin=PIN_PROBE_SQL)
    options = dict(driver=str(args.duckdb_library), entrypoint="duckdb_adbc_init", autocommit=True)
    with (
        dbapi.connect(**options, db_kwargs={"allow_unsigned_extensions": "true"}) as reader,
        dbapi.connect(**options, db_kwargs={"path": str(destination)}) as consumer,
        reader.cursor() as source,
        consumer.cursor() as sink,
    ):
        source.execute("SELECT library_version, source_id FROM pragma_version()")
        if source.fetchone() != (DUCKDB_PIN_VERSION, DUCKDB_PIN_SOURCE):
            raise RuntimeError("Expected the pinned DuckDB ADBC driver")
        source.execute("LOAD " + sql_literal(args.extension))
        source.execute(provision(graph, alias="air_routes"))
        source.execute("SESSION SET GRAPH air_routes")
        for name, dialect, statement in (
            ("gql_routes", "gql", ROUTES),
            ("cypher_routes", "cypher", ROUTES),
            ("empty_routes", "gql", ROUTES.replace("'ATL'", "'ORD'")),
        ):
            source.execute("SET SESSION qw_graph_dialect = " + sql_literal(dialect))
            source.execute(statement)
            sink.adbc_ingest(name, source.fetch_arrow_table())
        # The DuckDB ADBC driver binds by position to the graph statement's named parameter.
        bound = ROUTES.replace("'ATL'", "$origin")
        for name, code in (("bound_atl", "ATL"), ("bound_quoted", "A'TL")):
            source.execute(bound, (code,))
            sink.adbc_ingest(name, source.fetch_arrow_table())
        source.execute("MATCH (o:airport)-[e:route]->(d:airport) RETURN e AS edge")
        sink.adbc_ingest("graph_edges", source.fetch_arrow_table())
    run_cases(args.duckdb_unittest, scratch, {"QW_CLIENT_DB": destination}, [HERE / "results.test"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("duckdb-library", "duckdb-unittest", "extension", "lbug"):
        parser.add_argument("--" + flag, required=True, type=lambda value: Path(value).resolve(strict=True))
    with tempfile.TemporaryDirectory(prefix="qw-public-client-") as directory:
        run(parser.parse_args(), Path(directory).resolve())
