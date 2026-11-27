"""An ordered graph-to-Parquet join on the LSQB creator projection."""

from hashlib import file_digest
from heapq import nsmallest
from pathlib import Path

from micro_workloads import edge_rows


CASE_ID = "directory_join_topk"
TOP_K = 2
SCHEMA = [
    ["route_id", "BIGINT"],
    ["destination_id", "BIGINT"],
    ["directory_id", "BIGINT"],
    ["destination_name", "VARCHAR"],
]
SQL = f"""SELECT g.mid AS route_id, g.author AS destination_id, d.directory_id, d.destination_name
FROM GRAPH_TABLE (social MATCH (m:Message)-[r:Message_hasCreator_Person]->(p:Person)
                  COLUMNS (p.PersonId AS author, m.MessageId AS mid)) AS g
JOIN read_parquet(getvariable('qw_directory_join_topk_path')) AS d ON d.destination_id = g.author
ORDER BY g.mid DESC NULLS LAST, g.author, d.directory_id
LIMIT {TOP_K}"""
DIRECTORY_FILE = "directory_join_topk.parquet"


def graph_rank(edge):
    author, mid = edge
    return -mid, author


def directory_digest(path):
    with path.open("rb") as source:
        return file_digest(source, "sha256").hexdigest()


def prepare(edges_path: Path, directory: Path):
    """Write the directory and compute its ordered result from the edge CSV."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    leading = nsmallest(TOP_K, edge_rows(edges_path), key=graph_rank)
    unmatched = {author for author, _ in leading}
    qualifying = min(
        (edge for edge in edge_rows(edges_path) if edge[0] not in unmatched),
        key=graph_rank,
        default=None,
    )
    if qualifying is None:
        raise ValueError("Directory top-k fixture needs a creator outside the top raw graph rows")

    author, _ = qualifying
    directory_rows = [[author, 2, "Secondary"], [author, 1, "Primary"]]
    directory.mkdir(parents=True, exist_ok=True)
    parquet = directory / DIRECTORY_FILE
    destinations, directory_ids, names = zip(*directory_rows)
    pq.write_table(pa.table({
        "destination_id": pa.array(destinations, type=pa.int64()),
        "directory_id": pa.array(directory_ids, type=pa.int64()),
        "destination_name": pa.array(names, type=pa.string()),
    }), parquet)

    joined = (
        [mid, destination, directory_id, name]
        for creator, mid in edge_rows(edges_path) if creator == author
        for destination, directory_id, name in directory_rows
    )
    expected = nsmallest(TOP_K, joined, key=lambda row: (-row[0], row[1], row[2]))
    return {"directory_rows": directory_rows, "directory_sha256": directory_digest(parquet)}, expected


def setup_sql(parameters, directory: Path):
    parquet = (directory / DIRECTORY_FILE).resolve()
    if directory_digest(parquet) != parameters["directory_sha256"]:
        raise ValueError("Benchmark directory Parquet does not match its SHA-256")
    escaped = str(parquet).replace("'", "''")
    return [f"SET VARIABLE qw_directory_join_topk_path = '{escaped}'"]


def setup(cursor, parameters, directory: Path):
    for statement in setup_sql(parameters, directory):
        cursor.execute(statement)
