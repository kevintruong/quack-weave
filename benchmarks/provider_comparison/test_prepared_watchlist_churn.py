"""Check the independent watchlist churn oracle and prepared execution tape."""

import json
from pathlib import Path
import tempfile
import unittest

import pyarrow as pa

import prepared_watchlist_churn as churn


EDGES = "3,31\n1,10\n1,10\n1,11\n2,20\n2,21\n3,32\n4,40\n-1000000000,43\n"
EXPECTED = [[1, 1, 6, 62], [2, 2, 4, 82], [3, 3, 4, 126]]


class RecordingCursor:
    def __init__(self, *, results=(), row_counts=()):
        self.statements = []
        self.results = iter(results)
        self.row_counts = iter(row_counts)

    def execute(self, statement):
        self.statements.append(statement)

    def fetch_arrow_table(self):
        return next(self.results)

    def fetchone(self):
        rows = next(self.row_counts)
        plan = {"operator": [{"type": "TABLE_SCAN", "name": "QW_GRAPH_QUERY", "intermediate_rows": rows}]}
        return "analyzed_plan", json.dumps(plan)


class PreparedWatchlistChurnTests(unittest.TestCase):
    def fixture(self, directory, rows=EDGES):
        path = directory / "edges.csv"
        path.write_text("author,mid\n" + rows, encoding="utf-8")
        return path

    def test_tape_matches_independent_oracle_and_is_stable(self):
        with tempfile.TemporaryDirectory() as scratch:
            directory = Path(scratch)
            parameters, expected = churn.prepare(self.fixture(directory), directory)
            reversed_rows = "\n".join(reversed(EDGES.splitlines())) + "\n"
            replay = churn.prepare(self.fixture(directory, reversed_rows), directory)

        self.assertEqual((parameters, expected), replay)
        self.assertEqual(expected, EXPECTED)
        for step, size, hit in zip(parameters["epochs"], (63, 64, 65), (1, 2, 3)):
            keys = step["keys"]
            self.assertEqual(len({key for key in keys if key is not None}), size)
            self.assertEqual(len(keys), size + 2)
            self.assertEqual(keys.count(hit), 2)
            self.assertEqual(keys.count(None), 1)
            self.assertEqual({key for key in keys if key is not None} & {1, 2, 3, 4, -1000000000}, {hit})

    def test_one_prepare_serves_all_epochs_and_receipts_keep_execution_order(self):
        with tempfile.TemporaryDirectory() as scratch:
            directory = Path(scratch)
            parameters, expected = churn.prepare(self.fixture(directory), directory)
            results = [pa.table({name: pa.array([value], type=pa.int64())
                                 for (name, _), value in zip(churn.SCHEMA[1:], row[1:])})
                       for row in expected]
            cursor = RecordingCursor(results=results)
            churn.setup(cursor, parameters, directory)
            table = churn.execute(cursor, parameters)

        self.assertEqual(table.column_names, [name for name, _ in churn.SCHEMA])
        self.assertEqual([list(record.values()) for record in table.to_pylist()], expected)
        self.assertEqual(sum(statement.startswith("PREPARE ") for statement in cursor.statements), 1)
        self.assertEqual(sum(statement.startswith("DELETE FROM ") for statement in cursor.statements), 3)
        executes = [statement for statement in cursor.statements if statement.startswith("EXECUTE ")]
        self.assertEqual(len(executes), 3)
        self.assertEqual(len(set(executes)), 1)

    def test_diagnostic_preserves_the_cap_transition(self):
        with tempfile.TemporaryDirectory() as scratch:
            directory = Path(scratch)
            parameters, _ = churn.prepare(self.fixture(directory), directory)
        cursor = RecordingCursor(row_counts=[3, 2, 9])
        routes = iter([("runtime_exact", "exact_keys"), ("runtime_exact", "exact_keys"), ("host", "key_cap")])

        def diagnostic(connection, rows):
            self.assertIs(connection, cursor)
            route, offer = next(routes)
            return {"scan_rows": rows, "applied_route": route, "admitted_generation": "one",
                    "watchlist_offers": [offer]}

        summary = churn.diagnose(cursor, parameters, diagnostic)
        self.assertEqual(summary["scan_rows"], 14)
        self.assertIsNone(summary["applied_route"])
        self.assertIn("applied_route", summary["unavailable"])
        self.assertEqual(summary["admitted_generation"], "one")
        observed = [(s["epoch"], s["distinct_keys"], s["applied_route"], s["watchlist_offers"])
                    for s in summary["steps"]]
        self.assertEqual(observed, [
            (1, 63, "runtime_exact", ["exact_keys"]),
            (2, 64, "runtime_exact", ["exact_keys"]),
            (3, 65, "host", ["key_cap"]),
        ])
        self.assertEqual(sum("EXPLAIN (ANALYZE, FORMAT JSON) EXECUTE " in stmt for stmt in cursor.statements), 3)

    def test_requires_three_distinct_authors(self):
        with tempfile.TemporaryDirectory() as scratch:
            directory = Path(scratch)
            with self.assertRaisesRegex(ValueError, "three distinct creator"):
                churn.prepare(self.fixture(directory, "1,10\n2,20\n"), directory)


if __name__ == "__main__":
    unittest.main()
