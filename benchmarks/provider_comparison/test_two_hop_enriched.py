"""Two-hop enrichment preserves both the provider and host join bags."""
import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import two_hop_enriched as workload


class TwoHopEnrichedTests(unittest.TestCase):
    def prepare(self, rows):
        with TemporaryDirectory(prefix="qw-two-hop-") as folder:
            directory = Path(folder)
            edges = directory / "edges.csv"
            with edges.open("w", encoding="utf-8", newline="") as target:
                writer = csv.writer(target)
                writer.writerow(("author", "mid"))
                writer.writerows(rows)
            return workload.prepare(edges, directory)

    def test_two_edge_bag_and_duplicate_enrichment_are_stable(self):
        edges = [(9, 11), (8, 1), (9, 11), (9, 3), (7, 3), (9, 3), (7, 13)]
        parameters, expected = self.prepare(edges)
        self.assertEqual((parameters, expected), self.prepare(reversed(edges)))
        self.assertEqual(parameters["seed"], 3)
        self.assertIn([3, 0, True], parameters["attributes"])
        self.assertIn([None, 0, True], parameters["attributes"])
        self.assertIn([11, 0, False], parameters["attributes"])
        self.assertEqual(expected, [[7, 1, 1, 13], [9, 0, 8, 88]])

    def test_duplicate_anchor_alone_does_not_count_as_a_sibling(self):
        with self.assertRaisesRegex(ValueError, "distinct sibling"):
            self.prepare([(9, 3), (9, 3), (7, 4)])

    def test_checksum_uses_sql_remainder_for_negative_message_ids(self):
        _, expected = self.prepare([(4, -9), (4, -7)])
        self.assertEqual(expected, [[4, 0, 2, -14]])


if __name__ == "__main__":
    unittest.main()
