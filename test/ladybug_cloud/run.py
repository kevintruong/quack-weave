#!/usr/bin/env python3
"""Run the native Ladybug cloud SQLLogic cases against a loopback object store."""

import argparse
import csv
from hashlib import file_digest, shake_256
import json
from pathlib import Path
import platform
import sys
import tempfile
from threading import Event
from time import monotonic

from fixture import Object, read_only_store


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "stabilization"))
from run_sqllogictest import (
    DUCKDB_PIN_VERSION,
    PIN_PROBE_SQL,
    ladybug,
    report_artifact,
    run_cases,
)


def checkpointed_graph(lbug, directory):
    graph = directory / "graph.lbdb"
    padding = directory / "padding.csv"
    with padding.open("w", encoding="ascii", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("id", "payload"))
        for row_id in range(256):
            writer.writerow((row_id, shake_256(str(row_id).encode("ascii")).hexdigest(4096)))

    ladybug(lbug, graph, f"""
CREATE NODE TABLE Person(id INT64 PRIMARY KEY, name STRING);
CREATE NODE TABLE Padding(id INT64 PRIMARY KEY, payload STRING);
CREATE REL TABLE FOLLOWS(FROM Person TO Person, id INT64, weight INT64);
CREATE (:Person {{id: 1, name: 'Alice'}}), (:Person {{id: 2, name: 'Bob'}}),
       (:Person {{id: 3, name: 'Carol'}}), (:Person {{id: 4, name: 'Dina'}});
MATCH (a:Person {{id: 1}}), (b:Person {{id: 2}})
CREATE (a)-[:FOLLOWS {{id: 10, weight: 7}}]->(b), (a)-[:FOLLOWS {{id: 11}}]->(b);
MATCH (a:Person {{id: 1}}), (b:Person {{id: 3}}) CREATE (a)-[:FOLLOWS {{id: 12, weight: 11}}]->(b);
MATCH (a:Person {{id: 2}}), (b:Person {{id: 4}}) CREATE (a)-[:FOLLOWS {{id: 40, weight: 5}}]->(b);
COPY Padding FROM '{str(padding).replace("'", "''")}' (header=true);
CHECKPOINT;
""")
    wal = graph.with_suffix(".lbdb.wal")
    if wal.exists() and wal.stat().st_size:
        raise AssertionError("Fixture retained a pending write-ahead log")
    return graph


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duckdb-unittest", required=True, type=Path)
    parser.add_argument("--extension", required=True, type=Path)
    parser.add_argument("--lbug", required=True, type=Path)
    parser.add_argument("--duckdb-httpfs", type=Path)
    args = parser.parse_args()
    unittest = args.duckdb_unittest.resolve(strict=True)
    extension = args.extension.resolve(strict=True)
    lbug = args.lbug.resolve(strict=True)
    httpfs = args.duckdb_httpfs
    if httpfs is None:
        host = "osx_arm64" if platform.system() == "Darwin" else "linux_arm64"
        httpfs = Path.home() / ".duckdb" / "extensions" / DUCKDB_PIN_VERSION / host / "httpfs.duckdb_extension"
    if not httpfs.is_file():
        parser.error(f"Provide the pinned DuckDB httpfs extension via --duckdb-httpfs. Missing {httpfs}.")

    with tempfile.TemporaryDirectory(prefix="qw-ladybug-cloud-") as folder:
        scratch = Path(folder).resolve()
        fixture_dir, test_dir = scratch / "fixture", scratch / "sqllogic"
        fixture_dir.mkdir()
        test_dir.mkdir()
        graph = checkpointed_graph(lbug, fixture_dir)
        report_artifact(extension)
        for dependency in (graph, lbug, httpfs):
            with dependency.open("rb") as handle:
                identity = {"name": str(dependency), "sha256": file_digest(handle, "sha256").hexdigest()}
            print("[QW_CLOUD_DEPENDENCY] " + json.dumps(identity), flush=True)
        data = graph.read_bytes()
        s3_secret = "qw-s3-fixture-key"
        clean_objects = {
            "/qw-s3-fixture/snapshots/graph.lbdb": Object(
                data, "qw-s3-fixture", s3_secret, token="qw-s3-fixture-token"
            ),
            "/qw-gcs-fixture/snapshots/graph.lbdb": Object(data, "qw-gcs-fixture", secret="qw-gcs-fixture-key"),
        }
        rejected_sidecars = {
            "/qw-s3-fixture/snapshots/dirty.lbdb.wal": (b"nonempty fixture WAL", 200),
            "/qw-s3-fixture/snapshots/denied.lbdb.wal": (403, 403),
        }
        objects = {
            **clean_objects,
            **{
                path.removesuffix(".wal"): Object(
                    data, "qw-s3-fixture", s3_secret, token="qw-s3-fixture-token", wal=wal
                )
                for path, (wal, _) in rejected_sidecars.items()
            },
        }
        run_cases(unittest, test_dir, {}, stdin=PIN_PROBE_SQL)
        with read_only_store(objects) as server:
            variables = {
                "QW_EXT": extension,
                "QW_LOAD_DUCKDB_HTTPFS": "LOAD '" + str(httpfs.resolve()).replace("'", "''") + "'",
                "QW_LADYBUG_CLOUD_FIXTURE_ENDPOINT": server.endpoint,
            }
            cases = HERE / "sqllogic"
            run_cases(unittest, test_dir, variables, [cases / "cloud_admission.test"])
            if server.requests:
                raise AssertionError(f"Rejected registrations contacted the object store: {server.requests}")
            try:
                run_cases(unittest, test_dir, variables, [cases / "cloud_native_attach.test"])
            finally:
                if server.unexpected:
                    raise AssertionError(f"Unexpected object-store requests: {server.unexpected}")

            for path in clean_objects:
                if not server.requests["HEAD", path, 200]:
                    raise AssertionError(f"No successful HEAD for {path}")
                if not any(target == path and length < len(data) for target, length in server.range_lengths):
                    raise AssertionError(f"No partial range read for {path}")
            for path, (_, status) in rejected_sidecars.items():
                if not server.requests["HEAD", path, status]:
                    raise AssertionError(f"No HEAD with status {status} for {path}")
                if server.requests["GET", path.removesuffix(".wal"), 206]:
                    raise AssertionError(f"Read graph bytes despite its unusable sidecar: {path}")
            print(f"Ladybug cloud fixture observed {sum(server.range_lengths.values())} ranged GETs and no mutations.")

        path = "/qw-s3-fixture/snapshots/slow.lbdb"
        wal_path = path + ".wal"
        finished = Event()
        delayed = Object(data, "qw-s3-fixture", s3_secret, token="qw-s3-fixture-token", hold_wal_head=finished)
        with read_only_store({path: delayed}) as server:
            variables["QW_LADYBUG_CLOUD_FIXTURE_ENDPOINT"] = server.endpoint
            try:
                run_cases(unittest, test_dir, variables, [cases / "cloud_registration_timeout.test"])
                head_started = server.held_wal_heads.get(wal_path)
                if head_started is None or server.requests["HEAD", wal_path, 404]:
                    raise AssertionError("Registration must time out while the signed WAL HEAD is held")
                if server.unexpected or server.range_lengths:
                    raise AssertionError(f"Unexpected HTTP during the stalled WAL HEAD: {server.requests}")
                elapsed_ms = (monotonic() - head_started) * 1000
                print(f"SQLLogic finished {elapsed_ms:.0f} ms after the stalled HEAD started, before its response.")
            finally:
                finished.set()


if __name__ == "__main__":
    main()
