#!/usr/bin/env python3
"""Exercise GQL bind admission with the packaged native extension."""

import argparse
from pathlib import Path
import tempfile
import unittest

from mvp1_acceptance import (
    FIXTURE,
    TRAVERSAL,
    duckdb,
    expect_failure,
    expect_rows,
    graph_query,
    ladybug,
    provision,
    sql_literal,
)


GQL_MATCH = "MATCH (a:Document)-[:LINKS_TO]->(b:Document)"
GQL_SELECT = f"{GQL_MATCH} WHERE a.id = 100 RETURN b.id AS document_id"
EXTRA_FIXTURE = r"""
CREATE (d:Document {id: 103, title: 'Zoë; O\'Brien\\path', active: true});
MATCH (a:Document {id: 100}), (b:Document {id: 103}) CREATE (a)-[:LINKS_TO]->(b);
MATCH (a:Document {id: 101}) CREATE (a)-[:LINKS_TO]->(a);
"""


class BindTests(unittest.TestCase):
    def select(self, query, dialect="gql", explain=""):
        function = graph_query(query, alias="KG", dialect=dialect)
        return duckdb(
            self.options.duckdb,
            self.setup + f"{explain}SELECT * FROM {function} ORDER BY document_id;\n",
        )

    def test_explicit_gql_and_cypher_dialects(self):
        expect_rows(self.select(GQL_SELECT, "GqL"), [["101"], ["103"]])
        expect_rows(self.select(TRAVERSAL, "CyPhEr"), [["101"], ["103"]])

    def test_unsupported_payload_never_falls_back_to_cypher(self):
        expect_rows(self.select(TRAVERSAL, "cypher"), [["101"], ["103"]])
        expect_failure(self.select(TRAVERSAL), "QW_GQL_SUBSET")
        expect_failure(self.select("INSERT (:Document)"), "QW_GQL_SUBSET")

    def test_malformed_gql_fails_in_explain_bind_with_location(self):
        result = self.select(f"{GQL_MATCH}\nRETURN", explain="EXPLAIN ")
        expect_failure(result, "QW_GQL_PARSE")
        self.assertIn("line 2", result.stderr)

    def test_filter_matches_native_where_for_typed_literals(self):
        gql_literal = r"'Zoë; O''Brien\\path'"
        cypher_literal = r"'Zoë; O\'Brien\\path'"
        projections = "RETURN b.id AS document_id"
        predicates = [
            (f"b.title = {gql_literal}", f"b.title = {cypher_literal}", [["103"]]),
            ("b.active <> false", "b.active <> false", [["101"], ["101"], ["103"]]),
            ("a.id = +100", "a.id = 100", [["101"], ["103"]]),
        ]
        for gql_predicate, cypher_predicate, rows in predicates:
            with self.subTest(predicate=gql_predicate):
                for prefix in ("FILTER", "FILTER WHERE"):
                    expect_rows(self.select(f"{GQL_MATCH} {prefix} {gql_predicate} {projections}"), rows)
                expect_rows(
                    self.select(f"{GQL_MATCH} WHERE {cypher_predicate} {projections}", "cypher"),
                    rows,
                )

    def test_gql_binding_rejects_ambiguous_or_unresolved_variables(self):
        invalid_queries = (
            f"{GQL_MATCH} RETURN c.id AS document_id",
            f"{GQL_MATCH} WHERE c.id = 100 RETURN b.id AS document_id",
            "MATCH (a:Document)-[:LINKS_TO]->(A:Document) RETURN A.id AS document_id",
            f"{GQL_MATCH} RETURN b.id AS document_id, a.id AS DOCUMENT_ID",
        )
        for query in invalid_queries:
            with self.subTest(query=query):
                result = self.select(query, explain="EXPLAIN ")
                expect_failure(result, "QW_GQL_SUBSET")
                self.assertIn("line 1", result.stderr)

        repeated = "MATCH (a:Document)-[:LINKS_TO]->(a:Document) RETURN a.id AS document_id"
        expect_rows(self.select(repeated), [["101"]])

    def test_gql_unavailable_in_the_cypher_only_build(self):
        expect_failure(self.select(GQL_SELECT, explain="EXPLAIN "), "QW_GQL_UNAVAILABLE")
        expect_rows(self.select(TRAVERSAL, "cypher"), [["101"], ["103"]])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duckdb", required=True)
    parser.add_argument("--lbug", required=True)
    parser.add_argument("--extension", required=True, type=Path)
    parser.add_argument("--without-frontend", action="store_true")
    options = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="qw-gql-bind-") as directory:
        graph = Path(directory) / "documents.lbdb"
        ladybug(options.lbug, graph, FIXTURE + EXTRA_FIXTURE)
        BindTests.options = options
        BindTests.setup = (
            f"LOAD {sql_literal(options.extension.resolve(strict=True))};\n" + provision(graph)
        )
        unavailable = "test_gql_unavailable_in_the_cypher_only_build"
        suite = unittest.TestSuite(
            BindTests(name)
            for name in unittest.defaultTestLoader.getTestCaseNames(BindTests)
            if (name == unavailable) == options.without_frontend
        )
        return unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful()


if __name__ == "__main__":
    raise SystemExit(not main())
