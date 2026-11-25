"""Compare both releases in alternating order, including outer SQL predicates."""
import argparse
import json
import math
import platform
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run

OUTER = f"SELECT mid FROM {run.PAIRS} WHERE author = {run.KEYS[0]}"
VIA_VIEW = f"SELECT mid FROM planning_pairs WHERE author = {run.KEYS[0]}"
CASES = {**run.CASES, "outer_where": ("gql", OUTER), "view_where": ("gql", VIA_VIEW)}
OUTER_FORMS = ("outer_where", "view_where")


def child(args):
    request = json.load(sys.stdin)
    observed = {}
    failed = {}
    timings = []
    with run.cursor(args) as (cur, setup):
        cur.execute("CREATE TEMP VIEW planning_pairs AS SELECT * FROM " + run.PAIRS)
        for name in OUTER_FORMS:
            try:
                cur.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + CASES[name][1])
                (observed[name],) = run.provider_rows(json.loads(cur.fetchone()[1])["operator"])
            except run.dbapi.Error as error:
                if args.release != "baseline" or args.provider != "relate" or "QW_EXECUTION" not in str(error):
                    raise
                # Confirm this is also an execution failure outside EXPLAIN.
                try:
                    run.fetch(cur, CASES[name][1])
                except run.dbapi.Error as query_error:
                    if "QW_EXECUTION" not in str(query_error):
                        raise
                    failed[name] = str(query_error)
                else:
                    raise
            if args.release == "candidate" and observed.get(name) != request["expected"]["graph_table_where"][0]:
                raise AssertionError(f"{args.provider} {name}: {observed}")
        for iteration in range(args.runs + 1):
            names = [name for name in CASES if name not in failed]
            random.Random(7411 + 101 * args.block + iteration).shuffle(names)
            for name in names:
                dialect, sql = CASES[name]
                cur.execute("SET SESSION qw_graph_dialect = " + run.sql_literal(dialect))
                signature, timing = run.fetch(cur, sql)
                key = "graph_table_where" if name in OUTER_FORMS else name
                if signature != request["expected"][key]:
                    raise AssertionError(f"{args.provider} {name}: {signature}")
                if iteration:
                    timings.append({"case": name, "iteration": iteration, **timing})
    print(json.dumps({"block": args.block, "provider": args.provider, "release": args.release,
                      "setup": setup, "samples": timings, "provider_rows": observed, "failures": failed}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--library", type=Path, default=run.LIB)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--blocks", type=int, default=2)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--provider", choices=run.ENGINES, help=argparse.SUPPRESS)
    parser.add_argument("--release", choices=("baseline", "candidate"), help=argparse.SUPPRESS)
    parser.add_argument("--block", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--extension", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.provider:
        return child(args)
    if not all([args.baseline, args.candidate, args.out]) or args.blocks < 2 or args.blocks % 2 or args.runs < 1:
        parser.error("Supply baseline, candidate, output, positive repeats, and an even number of blocks >=2")
    reference = run.oracle(args.fixture)
    artifacts = {"baseline": args.baseline, "candidate": args.candidate}
    result = {"start_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
              "fixture": json.loads((args.fixture / "fixture.json").read_text()), "library_sha256": run.digest(args.library),
              "extensions": {k: run.digest(v) for k, v in artifacts.items()}, "cases": CASES,
              "expected": reference["expected"], "blocks": args.blocks, "runs": args.runs, "workers": [], "summary": {}}
    for block in range(args.blocks):
        providers = list(run.ENGINES)
        releases = list(artifacts)
        if block % 2:
            providers.reverse()
            releases.reverse()
        for provider in providers:
            for release in releases:
                cmd = [sys.executable, "-B", __file__, "--fixture", args.fixture, "--library", args.library,
                       "--provider", provider, "--release", release, "--extension", artifacts[release],
                       "--block", str(block), "--runs", str(args.runs)]
                process = subprocess.run(cmd, input=json.dumps({"expected": reference["expected"]}),
                                         capture_output=True, text=True)
                if process.returncode:
                    raise RuntimeError(f"{provider} {release} block {block + 1}: {process.stderr}")
                result["workers"].append(json.loads(process.stdout))
                print(f"{provider} {release} block {block + 1}/{args.blocks} verified", flush=True)
    for provider in run.ENGINES:
        summary = result["summary"][provider] = {}
        for name in CASES:
            summary[name] = {}
            for release in artifacts:
                workers = [w for w in result["workers"] if w["provider"] == provider and w["release"] == release]
                measured = sorted(s["wall_ms"] for w in workers for s in w["samples"] if s["case"] == name)
                expected = sum(args.runs for w in workers if name not in w["failures"])
                if len(measured) != expected:
                    raise AssertionError(f"Incomplete {provider} {release} {name} samples")
                summary[name][release] = {"n": len(measured), "p50_ms": median(measured) if measured else None,
                                          "p95_ms": measured[math.ceil(.95 * len(measured)) - 1] if measured else None}
    result["finish_utc"] = datetime.now(timezone.utc).isoformat()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
