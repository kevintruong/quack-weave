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
