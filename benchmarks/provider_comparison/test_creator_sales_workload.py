"""Check the recorded sales ranking against a hand-calculated ledger."""
from datetime import timedelta
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pyarrow as pa
import pyarrow.parquet as pq


class SalesWorkload(unittest.TestCase):
    def test_sales_oracle_counts_refunds_and_compares_ordered_windows(self):
        self.assertIsNotNone(find_spec("creator_sales_workload"), "Sales benchmark case is missing")
        import creator_sales_workload as sales

        rows = []

        def add(channel, cents=100, age=7, kind="sale", status="settled", content=10):
            rows.append(dict(channel=channel, amount_cents=cents, kind=kind, status=status,
                             booked_on=sales.CLOSE - timedelta(days=age), content_id=content))

        for channel in ("affiliate", "email", "storefront", "social"):
            for _ in range(5):
                add(channel)
        add("affiliate", -100, kind="refund")
        add("social", -500, kind="refund")
        add("affiliate", 600, age=30)
        add("email", 1000, age=0)
        add("email", 1000, age=31)
        add("email", 1000, status="pending")
        add("email", 1000, content=99)
        add("small", 10000)

        with TemporaryDirectory() as temp:
            path = Path(temp) / "sales.parquet"
            pq.write_table(pa.Table.from_pylist(rows), path)
            self.assertEqual(sales.oracle(path, pa.array([10])), [
                [7, "email", 5, 500], [7, "storefront", 5, 500], [7, "affiliate", 5, 400],
                [30, "affiliate", 6, 1000], [30, "email", 5, 500], [30, "storefront", 5, 500],
            ])
