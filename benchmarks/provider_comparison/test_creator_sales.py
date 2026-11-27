"""Check settlement and ranking semantics against hand-calculated channel totals."""
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

import creator_sales as bench


class CreatorSales(unittest.TestCase):
    def test_net_sales_windows_and_portfolio_membership(self):
        rows = []

        def add(channel, cents=100, age=7, kind="sale", status="settled", content=10):
            rows.append(dict(channel=channel, amount_cents=cents, kind=kind, status=status,
                             booked_on=bench.CLOSE - timedelta(days=age), content_id=content))

        for channel in ("affiliate", "email", "storefront", "social"):
            for _ in range(5):
                add(channel)
        for _ in range(5):
            add("marketplace", 10)  # Eligible, but below the top three.
        add("affiliate", -100, kind="refund")
        add("social", -500, kind="refund")  # Zero net sales drops the group.
        add("affiliate", 600, age=30)
        for age in (0, 31):
            add("email", 1000, age=age)
        add("email", 1000, status="pending")
        add("email", 1000, content=99)
        add("small", 10000)  # Below the five-purchase threshold.

        expected = {"7": [["email", 5, 500], ["storefront", 5, 500], ["affiliate", 5, 400]],
                    "30": [["affiliate", 6, 1000], ["email", 5, 500], ["storefront", 5, 500]]}
        with TemporaryDirectory() as temp:
            path = Path(temp) / "sales.parquet"
            pq.write_table(pa.Table.from_pylist(rows), path)
            answer, funnel = bench.oracle(path, pa.array([10]))
            self.assertEqual(answer, expected)
            self.assertEqual(funnel["settled_by_window"][7]["refunds"], 2)
            with bench.run.duckdb_cursor(SimpleNamespace(library=bench.run.LIB)) as (cur, _):
                parquet = "read_parquet(" + bench.run.sql_literal(path) + ")"
                cur.execute("CREATE TEMP TABLE sales_memory AS FROM " + parquet)
                cur.execute("CREATE TEMP TABLE portfolio AS SELECT 10::BIGINT AS content_id")
                for storage in bench.FACTS:
                    for days in bench.WINDOWS:
                        with self.subTest(storage=storage, days=days):
                            cur.execute(bench.sql("portfolio", storage, days).replace(bench.FACTS["parquet"], parquet))
                            self.assertEqual([list(row) for row in cur.fetchall()], expected[str(days)])
