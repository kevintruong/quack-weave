"""Check the tracker entry point and application workload evidence."""
import subprocess
import sys
import unittest
from pathlib import Path


class ApplicationWorkloads(unittest.TestCase):
    def test_tracker_lists_directory_join_for_both_hybrid_arms(self):
        tracker = Path(__file__).with_name("tracker.py")
        result = subprocess.check_output([sys.executable, "-B", str(tracker), "list"], text=True)
        self.assertIn("directory_join_topk\tqw_pgq\tqw_pgq_host", result.splitlines())

    def test_standalone_experiments_do_not_import_the_tracker_cli(self):
        modules = subprocess.check_output(
            [sys.executable, "-B", "-c",
             "import creator_sales, complex_cypher, sys; print('tracker' in sys.modules)"],
            cwd=Path(__file__).parent,
            text=True,
        )
        self.assertEqual(modules.strip(), "False")
