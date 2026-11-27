"""Directory top-k fixture and independent ordered oracle."""

from hashlib import file_digest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import pyarrow.parquet as pq

import directory_join_topk as workload


class DirectoryJoinTopK(unittest.TestCase):
    def setUp(self):
        scratch = TemporaryDirectory(prefix="qw directory 'fixture' ")
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.edges = self.root / "edges.csv"

    def test_highest_graph_rows_are_unmatched_and_visible_ties_are_ordered(self):
        self.edges.write_text("author,mid\n9,102\n11,101\n7,90\n4,90\n4,80\n4,5\n", encoding="utf-8")
        first_dir, second_dir = self.root / "first", self.root / "second"
        parameters, expected = workload.prepare(self.edges, first_dir)
        self.assertEqual(expected, [[90, 4, 1, "Primary"], [90, 4, 2, "Secondary"]])
        self.assertEqual(workload.prepare(self.edges, second_dir), (parameters, expected))
        self.assertNotIn(str(self.root), json.dumps(parameters))
        parquet, = first_dir.glob("*.parquet")
        with parquet.open("rb") as handle:
            self.assertEqual(parameters["directory_sha256"], file_digest(handle, "sha256").hexdigest())
        self.assertEqual(pq.read_table(parquet)["directory_id"].to_pylist(), [2, 1])
        self.assertIn("read_parquet(getvariable(", workload.SQL)

        statements = []
        workload.setup(SimpleNamespace(execute=statements.append), parameters, first_dir)
        self.assertEqual(statements, workload.setup_sql(parameters, first_dir))
        self.assertIn(str(parquet).replace("'", "''"), statements[0])

    def test_oracle_preserves_parallel_identical_edges(self):
        self.edges.write_text("author,mid\n9,102\n11,101\n4,90\n4,90\n4,80\n", encoding="utf-8")
        _, expected = workload.prepare(self.edges, self.root / "directory")
        self.assertEqual(expected, [[90, 4, 1, "Primary"], [90, 4, 1, "Primary"]])

    def test_requires_a_qualifying_creator_and_rejects_the_wrong_csv_schema(self):
        directory = self.root / "directory"
        self.edges.write_text("author,mid\n9,102\n11,101\n9,5\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "creator outside the top"):
            workload.prepare(self.edges, directory)
        self.edges.write_text("mid,author\n9,102\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "creator edge CSV"):
            workload.prepare(self.edges, directory)

    def test_setup_rejects_tampered_parquet_before_opening_it(self):
        self.edges.write_text("author,mid\n9,102\n11,101\n4,90\n", encoding="utf-8")
        directory = self.root / "directory"
        parameters, _ = workload.prepare(self.edges, directory)
        parquet, = directory.glob("*.parquet")
        with parquet.open("ab") as handle:
            handle.write(b"other contents")
        with self.assertRaisesRegex(ValueError, "directory Parquet.*SHA-256"):
            workload.setup_sql(parameters, directory)


if __name__ == "__main__":
    unittest.main()
