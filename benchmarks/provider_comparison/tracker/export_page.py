"""Export the benchmark page's chart data from verified tracker and notebook runs."""

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "docs/benchmark-data.js"


def load(path):
    content = path.read_bytes()
    return json.loads(content), hashlib.sha256(content).hexdigest()


def nearest_rank(samples, percentile):
    return sorted(samples)[math.ceil(len(samples) * percentile / 100) - 1]


def tracker_run(path, expected_protocol):
    report, source_hash = load(path)
    if report["protocol"] != expected_protocol:
        raise ValueError(f"{path} uses a different tracker protocol")
    if expected_protocol == 2 and not report.get("micro_sqllogic", {}).get("checks"):
        raise ValueError(f"{path} needs CM-LDBC SQLLogic verification")

    samples = defaultdict(list)
    crossings = defaultdict(list)
    for worker in report["workers"]:
        route = worker["provider"], worker["route"]
        for sample in worker["samples"]:
            if sample["repetition"] > 0:
                samples[*route, sample["case"]].append(sample["wall_ms"])
        for case, rows in worker.get("graph_scan_rows", {}).items():
            crossings[*route, case].append(rows)

    series = []
    for row in report["summary"]:
        key = tuple(row[field] for field in ("provider", "route", "case"))
        observed = samples.pop(key)
        p50, p95 = median(observed), nearest_rank(observed, 95)
        if (row["n"], row["p50_ms"], row["p95_ms"]) != (len(observed), p50, p95):
            raise ValueError(f"{path} has a summary mismatch for {key}")
        counts = crossings.get(key)
        series.append({
            **dict(zip(("provider", "route", "case"), key)),
            "p50_ns": round(p50 * 1_000_000), "p95_ns": round(p95 * 1_000_000),
            "n": len(observed), "rows": [min(counts), max(counts)] if counts else None,
        })
    if samples:
        raise ValueError(f"{path} has timed samples missing from its summary")
    return {
        "id": report["id"], "date": report["started_utc"][:10], "edges": report["edge_count"],
        "revision": report["workspace_head"], "extension_sha256": report["binaries"]["extension"],
        "library_sha256": report["binaries"]["duckdb_library"], "source_sha256": source_hash,
        "csv_sha256": report["fixture"]["files"]["edges.csv"]["sha256"], "series": series,
    }


def fanout_run(path):
    report, source_hash = load(path)
    series = []
    for row in report["cases"]:
        samples = row["host_prefilter_pairs_ns"]
        controls = row["host_host_pairs_ns"]
        gain = nearest_rank([host - filtered for host, filtered in samples], 50)
        noise = nearest_rank([abs(a - b) for a, b in controls], 95)
        if (row["median_paired_gain_ns"], row["aa_p95_abs_delta_ns"]) != (gain, noise):
            raise ValueError(f"{path} has a paired summary mismatch")
        for arm, (route, count) in enumerate((("qw_pgq_host", "host_rows"), ("qw_pgq", "prefilter_rows"))):
            p50, p95 = (nearest_rank([pair[arm] for pair in samples], p) for p in (50, 95))
            if (row["p50_ns"][arm], row["p95_ns"][arm]) != (p50, p95):
                raise ValueError(f"{path} has a percentile mismatch")
            series.append({
                "provider": row["provider"], "route": route, "case": row["offer"],
                "p50_ns": p50, "p95_ns": p95, "n": len(samples),
                "rows": [row[count], row[count]], "gain_ns": gain, "noise_ns": noise,
            })
    return {
        "edges": report["fixture"]["rows"], "revision": report["checkout"],
        "extension_sha256": report["extension_sha256"], "library_sha256": report["duckdb_library_sha256"],
        "source_sha256": source_hash, "csv_sha256": report["fixture"]["files"]["edges.csv"]["sha256"],
        "series": series,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sf1", type=Path, default=Path(__file__).with_name("sf1.json"))
    parser.add_argument("--micro", type=Path, required=True)
    parser.add_argument("--fanout", type=Path, nargs=2, required=True, metavar=("FIRST", "REPEAT"))
    parser.add_argument("--out", type=Path, default=OUTPUT)
    args = parser.parse_args()
    first, repeat = (fanout_run(path) for path in args.fanout)
    for field in ("edges", "csv_sha256", "extension_sha256", "library_sha256"):
        if first[field] != repeat[field]:
            raise ValueError(f"Fanout runs differ in {field}")
    if first["source_sha256"] == repeat["source_sha256"]:
        raise ValueError("Supply two distinct fanout reports")
    data = {
        "micro": [tracker_run(args.micro, 2)],
        "sf1": [tracker_run(args.sf1, 1)],
        "fanout": [first, repeat],
    }
    for runs in data.values():
        for run in runs:
            for row in run["series"]:
                if not (row["n"] > 0 and 0 < row["p50_ns"] <= row["p95_ns"]):
                    raise ValueError(f"Invalid timing series {row}")
    args.out.write_text(
        "// Generated by benchmarks/provider_comparison/tracker/export_page.py.\n"
        + "globalThis.quackWeaveBenchmarks = " + json.dumps(data, indent=2, allow_nan=False) + ";\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
