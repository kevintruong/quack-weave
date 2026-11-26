#!/usr/bin/env python3
"""Collect test-only observations and verify them with the pinned DuckDB runner."""

import argparse
import csv
from pathlib import Path
import subprocess
import sys
import tempfile

from run_sqllogictest import HERE, LADYBUG_VERSION, PIN_PROBE_SQL, ladybug, report_artifact, run_cases


PREFIX = "QW_OBSERVATION\t"
FIELDS = ("fixture_version", "case_id", "invocation_id", "sequence", "event", "outcome", "value")
ROOT = HERE.parent.parent


def collect(label, command, report_dir):
    result = subprocess.run(
        command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", check=False,
    )
    if report_dir is not None:
        (report_dir / f"{label}.log").write_text(result.stdout, encoding="utf-8")
    print(result.stdout, end="", flush=True)
    result.check_returncode()
    records = []
    for line in result.stdout.splitlines():
        if (payload := line.removeprefix(PREFIX)) != line:
            fields = payload.split("\t")
            if len(fields) != len(FIELDS):
                raise ValueError(f"Malformed observer record from {label}: {line!r}")
            records.append(fields)
    if not records:
        raise ValueError(f"{label} emitted no observer records")
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duckdb-unittest", required=True, type=Path)
    parser.add_argument("--duckdb-library", required=True, type=Path)
    parser.add_argument("--lbug", required=True, type=Path)
    parser.add_argument("--extension", required=True, type=Path)
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--observer-test-dir", type=Path, help="Directory containing prebuilt Rust test executables")
    args = parser.parse_args()
    unittest, library, lbug, extension = (
        path.resolve(strict=True)
        for path in (args.duckdb_unittest, args.duckdb_library, args.lbug, args.extension)
    )
    version = subprocess.check_output([lbug, "-v"], text=True).split()
    if not version or version[-1] != LADYBUG_VERSION:
        parser.error(f"Ladybug {LADYBUG_VERSION} is required")
    report_dir = args.report_dir
    if report_dir is not None:
        report_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="qw-observer-") as directory:
        scratch = Path(directory).resolve()
        run_cases(unittest, scratch, {}, stdin=PIN_PROBE_SQL)
        report_artifact(extension)
        graph = scratch / "graph.lbdb"
        ladybug(lbug, graph, (HERE / "fixtures/read_graph.cypher").read_text(encoding="utf-8"))
        records = []
        for label, crate in (("native", "rusty_quack"), ("core", "rusty_quack_core")):
            if args.observer_test_dir is None:
                command = ["cargo", "test", "--locked", "--package", crate]
                command.extend(["fixture_observer", "--"])
            else:
                command = [(args.observer_test_dir / crate).resolve(strict=True), "fixture_observer"]
            records.extend(collect("observer-" + label, [*command, "--nocapture", "--test-threads=1"], report_dir))
        records.extend(collect("observer-host", [
            sys.executable, "-B", HERE / "capture_host_observations.py", "--duckdb-lib", library,
            "--graph", graph, "--extension", extension,
        ], report_dir))
        observations = scratch / "observer-raw.csv"
        with observations.open("w", encoding="utf-8", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(FIELDS)
            writer.writerows(records)
        if report_dir is not None:
            (report_dir / observations.name).write_bytes(observations.read_bytes())
        run_cases(unittest, scratch, {"QW_OBSERVATIONS": observations},
                  [HERE / "sqllogic/observer_audit.test"])


if __name__ == "__main__":
    main()
