"""Compare the tracker SF1 workload on the same Ladybug snapshot on disk and in S3."""

import argparse
from base64 import b64decode
from contextlib import ExitStack
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import random
import subprocess
from time import perf_counter_ns
from urllib.parse import urlsplit

import run


ORACLE = Path(__file__).with_name("tracker") / "sf1.json"
CASES = ("gql_lookup", "graph_table_where", "full_scan_aggregate")
TIMEOUT_MS = 180_000
SEED = 913


def aws_json(message, *arguments):
    try:
        result = subprocess.run(
            ["aws", "--no-cli-pager", "--output", "json", *arguments],
            text=True, capture_output=True, check=True,
        )
        return json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, ValueError):
        raise RuntimeError(message) from None


def snapshot_head(args):
    metadata = aws_json(
        "Could not read the S3 snapshot checksum",
        "s3api", "head-object", "--bucket", args.object.netloc, "--key", args.object.path[1:],
        "--region", args.region, "--checksum-mode", "ENABLED",
    )
    checksum = metadata.get("ChecksumSHA256")
    if not checksum or metadata.get("ChecksumType") != "FULL_OBJECT":
        raise ValueError("S3 must expose a full-object SHA-256 checksum")
    return {
        "sha256": b64decode(checksum, validate=True).hex(),
        "bytes": metadata["ContentLength"],
        "etag": metadata["ETag"],
        "version": metadata.get("VersionId"),
        "last_modified": metadata["LastModified"],
    }


def connection(stack, args, arm):
    cursor, _ = stack.enter_context(run.duckdb_cursor(args))
    cursor.execute("LOAD " + run.sql_literal(args.extension))
    cursor.execute("LOAD " + (run.sql_literal(args.duckdb_httpfs) if args.duckdb_httpfs else "httpfs"))
    cursor.execute("SET GLOBAL qw_enable_remote_graphs = true")
    config = {"alias": run.GRAPH_ALIAS, "path": str(args.local) if arm == "local" else args.uri,
              "timeout_ms": TIMEOUT_MS}
    if arm == "s3":
        try:
            credentials = aws_json(
                "Could not resolve AWS CLI credentials",
                "configure", "export-credentials", "--format", "process",
            )
            fields = {"KEY_ID": credentials["AccessKeyId"], "SECRET": credentials["SecretAccessKey"],
                      "REGION": args.region, "SCOPE": args.uri}
            if credentials.get("SessionToken"):
                fields["SESSION_TOKEN"] = credentials["SessionToken"]
            options = ", ".join(f"{key} {run.sql_literal(value)}" for key, value in fields.items())
            cursor.execute(f"CREATE SECRET benchmark_reader IN connection (TYPE s3, {options})")
        except Exception:
            raise RuntimeError("Could not initialize connection-scoped AWS credentials") from None
        config["secret"] = "benchmark_reader"

    start = perf_counter_ns()
    cursor.execute("SET GLOBAL qw_ladybug_config = " + run.sql_literal(json.dumps(config)))
    register_ms = run.milliseconds(start)
    cursor.execute("SESSION SET GRAPH " + run.GRAPH_ALIAS)
    cursor.execute("SET SESSION qw_graph_dialect='gql'")
    cursor.execute("SET SESSION qw_enable_runtime_watchlist=false")
    cursor.execute("CALL enable_logging('QuackWeaveGraphRoute', level='info')")
    return cursor, register_ms


def schedule(block, arms):
    for iteration in range(4):
        cases = list(CASES)
        if iteration:
            random.Random(SEED + block * 4 + iteration).shuffle(cases)
        for index, case in enumerate(cases):
            pair = arms if (iteration + index) % 2 == 0 else arms[::-1]
            for arm in pair:
                yield iteration, case, arm


def observe(cursor, case, query, expected, schemas, seen):
    start = perf_counter_ns()
    try:
        cursor.execute(query)
        table = cursor.fetch_arrow_table()
    except Exception as error:
        if "QW_TIMEOUT" not in str(error):
            raise
        sample = {"status": "timeout", "error": "QW_TIMEOUT", "wall_ms": run.milliseconds(start)}
    else:
        elapsed = run.milliseconds(start)
        signature = run.signature([column.to_numpy(zero_copy_only=False) for column in table.columns])
        schema = [[field.name, str(field.type)] for field in table.schema]
        if signature != expected or schemas.setdefault(case, schema) != schema:
            raise ValueError(f"{case} disagrees with the SF1 result signature or matched schema")
        sample = {"status": "ok", "wall_ms": elapsed, "result": signature, "schema": schema}
        if table.num_rows == 1:
            sample["value"] = [str(column[0].as_py()) for column in table.columns]

    cursor.execute("SELECT message FROM duckdb_logs() WHERE type='QuackWeaveGraphRoute' ORDER BY timestamp")
    events = [row[0] for row in cursor.fetchall()]
    sample["dispatch"] = events[seen:]
    if sample["status"] == "ok" and sample["dispatch"] != ([] if case == "gql_lookup" else ["host"]):
        raise ValueError(f"{case} observed unexpected dispatch: {sample['dispatch']}")
    return sample, len(events)


def collect(args, report):
    schemas = {}
    for block, arms in enumerate((("local", "s3"), ("s3", "local"))):
        with ExitStack() as stack:
            cursors, seen = {}, dict.fromkeys(arms, 0)
            for arm in arms:
                cursors[arm], elapsed = connection(stack, args, arm)
                report["setup"].append({"block": block, "arm": arm, "register_ms": elapsed})
                print(f"registered {arm}, block {block}, {elapsed:.1f} ms", flush=True)

            def measure(iteration, case, arm, *, retry=False):
                print(f"start {block}/{iteration} {arm} {case}", flush=True)
                sample, seen[arm] = observe(
                    cursors[arm], case, report["queries"][case], report["expected"][case], schemas, seen[arm],
                )
                report["samples"].append({"block": block, "round": iteration, "warmup": iteration == 0,
                                          "arm": arm, "case": case, "retry": retry, **sample})
                print(f"{sample['status']} {block}/{iteration} {arm} {case} {sample['wall_ms']:.2f} ms", flush=True)

            for iteration, case, arm in schedule(block, arms):
                measure(iteration, case, arm)
            if block == 1:
                for case in sorted({sample["case"] for sample in report["samples"] if sample["status"] == "timeout"}):
                    for arm in arms:
                        measure(4, case, arm, retry=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", required=True, type=Path)
    parser.add_argument("--uri", required=True, help="S3 URI of the same checkpointed snapshot")
    parser.add_argument("--region", required=True)
    parser.add_argument("--extension", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="new JSON report file")
    parser.add_argument("--library", type=Path, default=run.LIB, help="pinned DuckDB ADBC library")
    parser.add_argument("--duckdb-httpfs", type=Path, help="matching signed httpfs extension")
    args = parser.parse_args()
    args.object = urlsplit(args.uri)
    if (args.object.scheme != "s3" or not args.object.netloc or len(args.object.path) < 2
            or args.object.query or args.object.fragment or args.object.username or ":" in args.object.netloc):
        parser.error("--uri must be an s3://bucket/key URI")
    if args.out.exists():
        parser.error("--out must name a new report file")
    for field in ("local", "extension", "library", "duckdb_httpfs"):
        path = getattr(args, field)
        if path is not None:
            setattr(args, field, path.resolve(strict=True))

    oracle = json.loads(ORACLE.read_text())
    local_sha = run.digest(args.local)
    before = snapshot_head(args)
    if local_sha != oracle["fixture"]["source_sha256"] or local_sha != before["sha256"]:
        raise ValueError("Local snapshot, S3 checksum, and tracker SF1 oracle must identify the same graph")
    if args.local.stat().st_size != before["bytes"]:
        raise ValueError("Local and S3 snapshot sizes differ")

    report = {
        "started": datetime.now(timezone.utc).isoformat(), "status": "failed",
        "source": {"local": str(args.local), "uri": args.uri, "region": args.region,
                   "sha256": local_sha, "before": before},
        "package": str(args.extension), "package_sha256": run.digest(args.extension),
        "host": str(args.library), "host_sha256": run.digest(args.library), "duckdb": "v2.0.1/8d78114e90",
        "system": platform.platform(), "client": "ADBC with fetch_arrow_table",
        "oracle_source": str(ORACLE.relative_to(run.ROOT)), "oracle_sha256": run.digest(ORACLE),
        "edge_count": oracle["edge_count"],
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=run.ROOT, text=True).strip(),
        "runner_sha256": run.digest(Path(__file__)),
        "queries": {case: run.CASES[case][1] for case in CASES},
        "expected": {case: oracle["expected"][case] for case in CASES},
        "threads": 1, "timeout_ms": TIMEOUT_MS, "seed": SEED, "setup": [], "samples": [],
    }
    try:
        collect(args, report)
        if any(sample["status"] == "timeout" for sample in report["samples"]):
            report["status"] = "incomplete"
            raise RuntimeError("SF1 schedule completed with query timeouts")
        report["status"] = "verified"
    finally:
        try:
            after = snapshot_head(args)
            report["source"]["after"] = after
            if after != before or run.digest(args.local) != local_sha:
                raise ValueError("Snapshot identity changed during measurement")
        except Exception:
            report["status"] = "source_unverified"
            raise
        finally:
            report["finished"] = datetime.now(timezone.utc).isoformat()
            run.publish(args.out, report)


if __name__ == "__main__":
    main()
