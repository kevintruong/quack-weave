"""Check SF1 result parity and profile an unmodified SQL VALUES join through QuackWeave.

Run with the project's ADBC/PyArrow/Ladybug environment and a read-only LSQB SF1
file. Use --baseline with an older extension to measure identical SQL before/after.
SF1 source: https://huggingface.co/datasets/ladybugdb/lsqb-sf1/blob/8283a51fa16c4d9fbc3c53ebde66252f7a41f3f6/lbdb/sf1.lbdb
Each engine runs in its own process. Timings cover execution and Arrow fetch
on an open connection; the first observation is excluded from the warm quantiles.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test"))
from mvp1_acceptance import provision, sql_literal

GRAPH_SHA = "84cd660cac88e20b627b40f2adf8de0c2c6d8693237c0d9f422469825721693f"
KEYS = [4398046519825, 2435, 6575, 28587302326226, -1]
PATTERN = "(m:Message)-[r:Message_hasCreator_Person]->(p:Person)"
NATIVE = f"""MATCH {PATTERN} WHERE p.PersonId IN {KEYS}
RETURN p.PersonId AS author, count(*) AS n, sum(m.MessageId % 1000003) AS fingerprint
ORDER BY author"""
VALUES = ", ".join(f"({key}::BIGINT)" for key in KEYS)
SQL = f"""SELECT g.author, count(*) AS n, sum(g.mid % 1000003) AS fingerprint
FROM GRAPH_TABLE (social MATCH {PATTERN} COLUMNS (p.PersonId AS author, m.MessageId AS mid)) AS g
JOIN (VALUES {VALUES}) AS watch(author) ON watch.author = g.author
GROUP BY g.author ORDER BY g.author"""


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def measure(fetch, runs):
    samples = []
    reference = None
    for i in range(runs + 1):
        start = time.perf_counter_ns()
        table = fetch()
        elapsed = (time.perf_counter_ns() - start) / 1e6
        rows = [[int(value) for value in row.values()] for row in table.to_pylist()]
        if i == 0:
            reference, first = rows, elapsed
        else:
            if rows != reference:
                raise ValueError("Repeated execution changed the result")
            samples.append(elapsed)
    return {"rows": reference, "first_ms": first, "samples_ms": samples,
            "p50_ms": statistics.median(samples),
            "p95_ms": sorted(samples)[math.ceil(.95 * runs) - 1]}


def provider_rows(nodes):
    for node in nodes:
        if node["type"] == "TABLE_SCAN" and node["name"].upper().startswith("QW_"):
            yield node["intermediate_rows"]
        yield from provider_rows(node.get("children", []))


def worker(args):
    if args.worker == "ladybug":
        from importlib.metadata import version
        import ladybug
        if version("ladybug") != "0.22.3":
            raise ValueError("Expected Ladybug 0.22.3")
        with ladybug.Database(str(args.graph), read_only=True) as graph, ladybug.Connection(graph) as conn:
            def fetch():
                with conn.execute(NATIVE) as result:
                    return result.get_as_arrow()
            return measure(fetch, args.runs)
    from adbc_driver_manager import dbapi
    package = args.extension if args.worker == "release" else args.baseline
    with dbapi.connect(driver=str(args.duckdb_library), entrypoint="duckdb_adbc_init", autocommit=True,
                       db_kwargs={"allow_unsigned_extensions": "true"}) as con, con.cursor() as cur:
        cur.execute("SELECT library_version, source_id FROM pragma_version()")
        if cur.fetchone() != ("v2.0.1", "8d78114e90"):
            raise ValueError("Expected the pinned DuckDB 2.0.1 ADBC driver")
        cur.execute("LOAD " + sql_literal(package))
        cur.execute(provision(args.graph, alias="social"))
        def fetch():
            cur.execute(SQL)
            return cur.fetch_arrow_table()
        report = measure(fetch, args.runs)
        cur.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + SQL)
        scans = list(provider_rows(json.loads(cur.fetchone()[1])["operator"]))
        if len(scans) != 1:
            raise ValueError(f"Expected one graph scan, observed {scans}")
        return {**report, "provider_rows": scans[0], "package_sha256": digest(package)}


def compare(args):
    if digest(args.graph) != GRAPH_SHA:
        raise ValueError("Expected the published LSQB SF1 Ladybug graph")
    engines = ["ladybug", "baseline", "release"] if args.baseline else ["ladybug", "release"]
    results = {}
    for engine in engines:
        output = subprocess.check_output([sys.executable, "-B", __file__, *sys.argv[1:],
                                          "--worker", engine], text=True)
        results[engine] = json.loads(output)
    reference = results["ladybug"]["rows"]
    if not all(item["rows"] == reference for item in results.values()):
        raise ValueError("Extension results differ from direct Ladybug")
    # Each watch key is distinct. The sum of the native groups is exactly the
    # number of matching edges, even though DuckDB returns only four groups.
    expected = sum(row[1] for row in reference)
    if results["release"]["provider_rows"] != expected:
        raise ValueError(f"Graph scan emitted {results['release']['provider_rows']} rows; expected {expected}")
    return {"graph_sha256": GRAPH_SHA, "sql": SQL, "cypher": NATIVE, "runs": args.runs, "engines": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("graph", "duckdb-library", "extension", "baseline"):
        parser.add_argument("--" + name, required=name != "baseline", type=lambda s: Path(s).resolve(strict=True))
    parser.add_argument("--runs", type=int, default=12)
    parser.add_argument("--worker", choices=["ladybug", "baseline", "release"], help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    print(json.dumps(worker(args) if args.worker else compare(args), indent=2))
