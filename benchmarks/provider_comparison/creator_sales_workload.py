"""Rank a creator's sales channels from a graph portfolio and a Parquet ledger."""

from collections import defaultdict
from datetime import date, timedelta
from hashlib import file_digest
from pathlib import Path


CASE_ID = "creator_sales_top_channels"
CLOSE = date(2025, 4, 1)  # Exclusive for both reporting windows.
WINDOWS = (7, 30)
CHANNELS = ("affiliate", "email", "livestream", "marketplace", "paid_social", "storefront")
CREATOR_ID = 4398046519825
SEED = 40261
ORDERS = 1_000_000
MIN_SALES = 5
TOP_K = 3
LEDGER_FILE = "sales.parquet"
SCHEMA = [
    ["days", "BIGINT"],
    ["channel", "VARCHAR"],
    ["sales", "BIGINT"],
    ["net_sales_cents", "BIGINT"],
]
PORTFOLIO_SQL = f"""SELECT DISTINCT g.content_id
FROM GRAPH_TABLE (social MATCH (m:Message)-[r:Message_hasCreator_Person]->(p:Person)
                  WHERE p.PersonId = {CREATOR_ID} COLUMNS (m.MessageId AS content_id)) AS g"""
window_values = ", ".join(f"({days}::BIGINT, DATE '{CLOSE - timedelta(days=days)}')" for days in WINDOWS)
SQL = f"""WITH windows(days, opened_on) AS (VALUES {window_values}),
channel_sales AS (
    SELECT w.days, s.channel, count(*) FILTER (WHERE s.kind = 'sale') AS sales,
           sum(s.amount_cents)::BIGINT AS net_sales_cents
    FROM creator_sales_portfolio AS p
    JOIN read_parquet(getvariable('qw_creator_sales_path')) AS s USING (content_id)
    JOIN windows AS w ON s.booked_on >= w.opened_on
    WHERE s.status = 'settled' AND s.booked_on >= DATE '{CLOSE - timedelta(days=max(WINDOWS))}'
      AND s.booked_on < DATE '{CLOSE}'
    GROUP BY w.days, s.channel
    HAVING count(*) FILTER (WHERE s.kind = 'sale') >= {MIN_SALES} AND sum(s.amount_cents) > 0
)
SELECT days, channel, sales, net_sales_cents FROM channel_sales
QUALIFY row_number() OVER (PARTITION BY days ORDER BY net_sales_cents DESC, channel) <= {TOP_K}
ORDER BY days, net_sales_cents DESC, channel"""


def make_ledger(path, mids, orders):
    """Write one seeded purchase per order plus optional partial refunds."""
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq

    rng = np.random.default_rng(SEED)
    content = rng.choice(mids, orders)
    channel = rng.choice(CHANNELS, orders, p=[.12, .21, .17, .19, .23, .08])
    day = rng.integers(0, 90, orders)
    cents = rng.integers(500, 25_001, orders)
    status = rng.choice(["settled", "pending", "void"], orders, p=[.88, .08, .04])
    refunds = np.flatnonzero((status == "settled") & (rng.random(orders) < .14))
    refund_count = len(refunds)
    days = np.concatenate([day, day[refunds] + rng.integers(1, 15, refund_count)])
    ids = np.arange(orders, dtype=np.int64)
    table = pa.table({
        "order_id": np.concatenate([ids, ids[refunds]]),
        "content_id": np.concatenate([content, content[refunds]]),
        "channel": np.concatenate([channel, channel[refunds]]),
        "booked_on": np.datetime64(CLOSE - timedelta(days=90)) + days.astype("timedelta64[D]"),
        "kind": np.concatenate([np.full(orders, "sale"), np.full(refund_count, "refund")]),
        "status": np.concatenate([status, rng.choice(["settled", "pending"], refund_count, p=[.9, .1])]),
        "amount_cents": np.concatenate([cents, -rng.integers(1, cents[refunds] + 1)]),
    })
    # Cluster by booked day for Parquet row-group pruning outside the report windows.
    pq.write_table(table.take(np.argsort(days, kind="stable")), path, compression="zstd", row_group_size=32768)


def oracle(path, portfolio):
    """Calculate ranked settled sales and signed net cents without executing SQL."""
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    groups = {days: defaultdict(lambda: [0, 0]) for days in WINDOWS}
    for batch in pq.ParquetFile(path).iter_batches():
        selected = batch.filter(pc.is_in(batch["content_id"], value_set=portfolio))
        for row in selected.to_pylist():
            if row["status"] != "settled":
                continue
            age = (CLOSE - row["booked_on"]).days
            for days, totals in groups.items():
                if 1 <= age <= days:
                    counts = totals[row["channel"]]
                    counts[0] += row["kind"] == "sale"
                    counts[1] += row["amount_cents"]

    ordered = []
    for days, totals in groups.items():
        eligible = [[days, channel, sales, net] for channel, (sales, net) in totals.items()
                    if sales >= MIN_SALES and net > 0]
        ordered.extend(sorted(eligible, key=lambda row: (-row[3], row[1]))[:TOP_K])
    return ordered


def ledger_digest(path: Path):
    with path.open("rb") as source:
        return file_digest(source, "sha256").hexdigest()


def prepare(edges_path: Path, directory: Path):
    """Generate the ledger and calculate the independent expected result."""
    import pyarrow.compute as pc
    import pyarrow.csv as csv
    import pyarrow.parquet as pq

    edges = csv.read_csv(edges_path)
    if edges.column_names != ["author", "mid"]:
        raise ValueError("Creator sales requires the matched creator edge CSV")
    portfolio = edges["mid"].filter(pc.equal(edges["author"], CREATOR_ID)).combine_chunks()
    if not len(portfolio) or pc.count_distinct(portfolio).as_py() != len(portfolio):
        raise ValueError(f"Creator sales requires a nonempty distinct portfolio for {CREATOR_ID}")

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / LEDGER_FILE
    make_ledger(path, edges["mid"].to_numpy(), ORDERS)
    expected = oracle(path, portfolio)
    ledger = pq.ParquetFile(path)
    return {
        "creator_id": CREATOR_ID,
        "portfolio_size": len(portfolio),
        "portfolio_sql": PORTFOLIO_SQL,
        "ledger_sha256": ledger_digest(path),
        "ledger_events": ledger.metadata.num_rows,
        "orders": ORDERS,
        "seed": SEED,
        "close_exclusive": CLOSE.isoformat(),
    }, expected


def setup_sql(parameters, directory: Path):
    path = (directory / LEDGER_FILE).resolve()
    if ledger_digest(path) != parameters["ledger_sha256"]:
        raise ValueError("Creator sales ledger Parquet does not match its SHA-256")
    escaped = str(path).replace("'", "''")
    return [
        f"SET VARIABLE qw_creator_sales_path = '{escaped}'",
        "CREATE TEMP VIEW creator_sales_portfolio AS " + parameters["portfolio_sql"],
    ]


def setup(cursor, parameters, directory: Path):
    for statement in setup_sql(parameters, directory):
        cursor.execute(statement)


def setup_staged(cursor):
    cursor.execute("SELECT content_id FROM creator_sales_portfolio")
    ids = cursor.fetch_arrow_table()
    cursor.execute("DROP VIEW creator_sales_portfolio")
    cursor.adbc_ingest("creator_sales_portfolio", ids, temporary=True)


def staged_sql():
    """Use a SQL-materialized portfolio for the SQLLogic replay."""
    return (
        "CREATE TEMP TABLE creator_sales_staged AS SELECT content_id FROM creator_sales_portfolio",
        "DROP VIEW creator_sales_portfolio",
        "ALTER TABLE creator_sales_staged RENAME TO creator_sales_portfolio",
    )
