"""Replay a changing watchlist against one prepared hybrid creator join."""

from collections import defaultdict
import json

from micro_workloads import CHECKSUM_MOD, HOST_THRESHOLD, edge_rows, values_sql


CASE_ID = "prepared_watchlist_churn"
# The C++ offer is capped by MAX_KEYS in crates/core/src/qw_query/runtime_watch.rs.
NATIVE_KEY_CAP = 64
DISTINCT_SIZES = (NATIVE_KEY_CAP - 1, NATIVE_KEY_CAP, NATIVE_KEY_CAP + 1)
# Use sparse misses, as in test/relate/watchlist_offer_diagnostics.test, so
# DuckDB can emit an exact IN filter rather than a dense range filter.
MISS_SPACING = 1_000_000_000
SQL = (
    f"SELECT g.author, count(*) AS matches, sum(g.mid % {CHECKSUM_MOD})::BIGINT AS checksum "
    "FROM GRAPH_TABLE (social MATCH (m:Message)-[r:Message_hasCreator_Person]->(p:Person) "
    "COLUMNS (p.PersonId AS author, m.MessageId AS mid)) AS g "
    "JOIN churn_watch AS w USING (author) GROUP BY g.author ORDER BY g.author"
)
SCHEMA = [[name, "BIGINT"] for name in ("epoch", "author", "matches", "checksum")]
QUERY = "EXECUTE churn_join"


def prepare(edges_path, directory):
    """Build a reproducible ordered tape and calculate its results from CSV edges."""
    totals = defaultdict(lambda: [0, 0])
    for author, mid in edge_rows(edges_path):
        totals[author][0] += 1
        residue = abs(mid) % CHECKSUM_MOD
        totals[author][1] += -residue if mid < 0 else residue

    if len(totals) < len(DISTINCT_SIZES):
        raise ValueError("Prepared watchlist churn needs at least three distinct creator IDs")
    authors = sorted(totals, key=lambda author: (-totals[author][0], author))[:len(DISTINCT_SIZES)]
    misses = []
    candidate = -MISS_SPACING
    while len(misses) < max(DISTINCT_SIZES) - 1:
        if candidate not in totals:
            misses.append(candidate)
        candidate -= MISS_SPACING

    epochs, expected = [], []
    for epoch, (author, distinct) in enumerate(zip(authors, DISTINCT_SIZES), 1):
        keys = [author, *misses[:distinct - 1], author, None]
        epochs.append({"epoch": epoch, "keys": keys})
        duplicates = keys.count(author)
        count, checksum = totals[author]
        expected.append([epoch, author, count * duplicates, checksum * duplicates])
    return {"epochs": epochs}, expected


def setup_sql(parameters, directory):
    """Set the watchlist budget and prepare the statement before timing."""
    return [
        f"SET dynamic_or_filter_threshold = {HOST_THRESHOLD}",
        "CREATE TEMP TABLE churn_watch(author BIGINT)",
        f"PREPARE churn_join AS {SQL}",
    ]


def setup(cursor, parameters, directory):
    for statement in setup_sql(parameters, directory):
        cursor.execute(statement)


def operations(parameters):
    """Yield each watchlist replacement and the same prepared execution."""
    for epoch in parameters["epochs"]:
        rows = [(key,) for key in epoch["keys"]]
        yield ["DELETE FROM churn_watch", f"INSERT INTO churn_watch VALUES {values_sql(rows)}"], QUERY


def execute(cursor, parameters):
    """Fetch all epochs; the caller's timer includes replacements and result collection."""
    import pyarrow as pa

    tables = []
    for epoch, (commands, query) in zip(parameters["epochs"], operations(parameters)):
        for command in commands:
            cursor.execute(command)
        cursor.execute(query)
        table = cursor.fetch_arrow_table()
        epoch_column = pa.array([epoch["epoch"]] * table.num_rows, type=pa.int64())
        tables.append(table.add_column(0, "epoch", epoch_column))
    return pa.concat_tables(tables)


def diagnose(cursor, parameters, scan_diagnostic):
    """Capture one profile and its scan-init logs for each untimed epoch."""
    from run import provider_rows

    cursor.execute("CALL enable_logging(level = 'info')")
    steps = []
    for epoch, (commands, query) in zip(parameters["epochs"], operations(parameters)):
        for command in commands:
            cursor.execute(command)
        cursor.execute("CALL truncate_duckdb_logs()")
        cursor.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + query)
        (rows,) = provider_rows(json.loads(cursor.fetchone()[1])["operator"])
        diagnostic = scan_diagnostic(cursor, rows)
        distinct = len({key for key in epoch["keys"] if key is not None})
        steps.append({**diagnostic, "epoch": epoch["epoch"], "distinct_keys": distinct})

    evidence = {"scan_rows": sum(step["scan_rows"] for step in steps), "steps": steps,
                "watchlist_offers": [offer for step in steps for offer in step["watchlist_offers"]]}
    unavailable = {}
    for field in ("applied_route", "admitted_generation"):
        values = [step[field] for step in steps]
        first = values[0]
        if first is not None and all(value == first for value in values):
            evidence[field] = first
        else:
            evidence[field] = None
            unavailable[field] = "incomplete across epochs" if None in values else "changes across epochs"
    if unavailable:
        evidence["unavailable"] = unavailable
    return evidence
