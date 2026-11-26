"""Exercise CM-LDBC selection and the independent result oracle."""

from pathlib import Path
import subprocess
import sys
import unittest

import tracker


class MicroWorkloads(unittest.TestCase):
    def test_lists_micro_cases_with_both_scan_routes(self):
        result = subprocess.check_output(
            [sys.executable, "-B", str(Path(tracker.__file__)), "list"], text=True
        )
        cases = {line.split("\t")[0]: line.split("\t")[1:] for line in result.splitlines()}
        for name in ("micro_creator_selective", "micro_creator_broad",
                     "micro_message_selective", "micro_creator_message"):
            self.assertEqual(cases[name], ["qw_pgq", "qw_pgq_host"])
        self.assertEqual(cases["table_watchlist"], ["qw_pgq"])

    def test_csv_oracle_keeps_duplicates_and_excludes_null_join_keys(self):
        from micro_workloads import expected_rows

        edges = [(595, 201), (600, 202), (None, 203), (595, 204)]
        relations = {
            "people": [[595, 1, 1], [595, 1, 1], [600, 2, 2], [None, 1, 0]],
            "messages": [[201, 7], [201, 7], [203, 9], [None, 0]],
        }
        self.assertEqual(expected_rows(edges, relations), {
            "micro_creator_selective": [(1, 4, 810)],
            "micro_creator_broad": [(1, 4, 810), (2, 1, 202)],
            "micro_message_selective": [(7, 2, 402), (9, 1, 203)],
            "micro_creator_message": [(1, 7, 4, 804)],
        })


if __name__ == "__main__":
    unittest.main()
