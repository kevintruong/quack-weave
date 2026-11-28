#!/usr/bin/env python3
"""Check Ladybug's packaged cloud filesystem against the pinned SQLLogic runner."""

import argparse
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from fixture import Object, ReadOnlyRequest, read_only_store
from xet_engine import check_xet

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cypher_acceptance import ladybug, sql_literal
from stabilization.run_sqllogictest import run_cases


SCHEMA = """\
CREATE NODE TABLE Vertex(id INT64 PRIMARY KEY);
CREATE REL TABLE Edge(FROM Vertex TO Vertex);
CREATE (:Vertex {id: 10}), (:Vertex {id: 20});
MATCH (a:Vertex {id: 10}), (b:Vertex {id: 20}) CREATE (a)-[:Edge]->(b);
CHECKPOINT;
"""
QUERY = "MATCH (a:Vertex)-[:Edge]->(b:Vertex) RETURN a.id AS src, b.id AS dst ORDER BY src, dst;"
OBJECT_PATH = "/graph-bucket/graph.lbdb"
KEY_ID = "fixture-key"
FIXTURE_SECRET = "fixture-secret"


class RangeFaultRequest(ReadOnlyRequest):
    def respond(self, status, *, length=0, content_range=None):
        if status != 206:
            return super().respond(status, length=length, content_range=content_range)
        fault = self.server.range_fault
        if fault == "redirect":
            self.server.requests[self.command, OBJECT_PATH, 302] += 1
            self.send_response(302)
            self.send_header("Location", "/never-follow")
            self.send_header("Content-Length", str(length))
            self.end_headers()
        elif fault == "wrong_range":
            total = content_range.split("/", 1)[1]
            super().respond(206, length=length, content_range=f"bytes 0-0/{total}")
        elif fault == "short_body":
            self.server.requests[self.command, OBJECT_PATH, 206] += 1
            self.send_response(206)
            self.send_header("Content-Range", content_range)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            # End the response cleanly before the requested range has arrived.
            self.wfile.write(b"0\r\n\r\n")
            self.wfile = DiscardWrites(self.wfile)


class DiscardWrites:
    def __init__(self, output):
        self.output = output

    def write(self, data):
        return len(data)

    def __getattr__(self, name):
        return getattr(self.output, name)


def observe_attachment(lbug, scratch, graph_bytes, scheme, prefix, dynamic_httpfs, fault=None):
    with read_only_store({OBJECT_PATH: Object(graph_bytes, KEY_ID, secret=FIXTURE_SECRET)}) as store:
        if fault:
            store.range_fault = fault
            store.RequestHandlerClass = RangeFaultRequest
        load = f"LOAD EXTENSION {sql_literal(dynamic_httpfs)};\n" if dynamic_httpfs else ""
        setup = (
            f"CALL {prefix}_ENDPOINT='{store.endpoint}';\n"
            f"CALL {prefix}_URL_STYLE='path';\n"
            f"CALL {prefix}_DISABLE_SSL=true;\n"
            f"CALL {prefix}_ACCESS_KEY_ID='{KEY_ID}';\n"
            f"CALL {prefix}_SECRET_ACCESS_KEY='{FIXTURE_SECRET}';\n"
            f"CALL {prefix}_SESSION_TOKEN='';\n"
            "CALL HTTP_CACHE_FILE=false;\n"
        )
        attach = f"ATTACH '{scheme}://graph-bucket/graph.lbdb' AS cloud (DBTYPE lbug);\n"
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(("S3_", "GCS_", "HTTP_"))}
        result = subprocess.run(
            [lbug, "-m", "jsonlines", "-s", "-b", "-p", scratch, ":memory:"],
            input=load + setup + attach + QUERY, text=True, capture_output=True,
            timeout=30, env=environment, check=False,
        )
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
        rows = [row for row in rows if "src" in row and "dst" in row]
        if fault:
            expected_errors = {
                "redirect": "from range GET",
                "wrong_range": "Unexpected HTTP Content-Range",
                "short_body": "Incomplete HTTP range response",
            }
            expected = expected_errors[fault]
            detail = result.stdout + result.stderr
            status = 302 if fault == "redirect" else 206
            if rows or expected not in detail or store.unexpected or not store.requests["GET", OBJECT_PATH, status]:
                raise AssertionError(
                    f"{scheme} {fault} did not fail at the range boundary:\n{detail}\n"
                    f"Observed HTTP requests: {store.requests}, unexpected: {store.unexpected}"
                )
            return (scheme, fault, True)
        if result.returncode or result.stderr or not rows:
            raise AssertionError(
                f"{scheme} attachment returned no usable rows:\n{result.stdout}{result.stderr}\n"
                f"Observed HTTP requests: {store.requests}"
            )
        reads = store.requests["GET", OBJECT_PATH, 206] > 0
        clean = not store.unexpected
        return [(scheme, row["src"], row["dst"], reads, clean) for row in rows]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lbug", required=True, type=Path)
    parser.add_argument("--duckdb-unittest", required=True, type=Path)
    parser.add_argument("--dynamic-httpfs", type=Path)
    args = parser.parse_args()
    lbug = args.lbug.resolve(strict=True)
    unittest = args.duckdb_unittest.resolve(strict=True)
    with TemporaryDirectory(prefix="qw-ladybug-engine-") as directory:
        scratch = Path(directory)
        fixture = scratch / "graph.lbdb"
        ladybug(lbug, fixture, SCHEMA)
        data = fixture.read_bytes()
        observations = scratch / "attachments.csv"
        with observations.open("w", newline="", encoding="utf-8") as output:
            writer = csv.writer(output)
            writer.writerow(("scheme", "src", "dst", "ranged_get", "only_reads"))
            for scheme, prefix in (("s3", "S3"), ("gs", "GCS")):
                writer.writerows(observe_attachment(lbug, scratch, data, scheme, prefix, args.dynamic_httpfs))
        invalid = scratch / "invalid-ranges.csv"
        with invalid.open("w", newline="", encoding="utf-8") as output:
            writer = csv.writer(output)
            writer.writerow(("scheme", "fault", "rejected"))
            for fault in ("redirect", "wrong_range", "short_body"):
                writer.writerow(observe_attachment(lbug, scratch, data, "s3", "S3", args.dynamic_httpfs, fault))
        run_cases(
            unittest, scratch, {
                "QW_ENGINE_ATTACH_OBSERVATIONS": observations,
                "QW_ENGINE_INVALID_RANGES": invalid,
            },
            [Path(__file__).with_name("engine_attach.test")],
        )
        if args.dynamic_httpfs is None:
            check_xet(lbug, unittest, scratch, data, QUERY, run_cases)


if __name__ == "__main__":
    main()
