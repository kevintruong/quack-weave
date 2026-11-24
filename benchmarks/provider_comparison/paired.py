"""Compare two QuackWeave releases on Ladybug with the SF1 benchmark worker."""
import argparse
import json
import math
from pathlib import Path
from statistics import median
import subprocess
import sys

from run import CASES, EXT, LIB, digest, oracle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--optimized", type=Path, default=EXT)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--library", type=Path, default=LIB)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--isolated", action="store_true", help="Run each workload in its own connection")
    args = parser.parse_args()

    reference = oracle(args.fixture)
    artifacts = {"baseline": args.baseline, "optimized": args.optimized}
    workers = []
    groups = [[case] for case in CASES] if args.isolated else [list(CASES)]
    for group in groups:
        request = json.dumps({"expected": reference["expected"], "cases": group})
        for block in range(4):
            order = list(artifacts) if block % 2 == 0 else list(reversed(artifacts))
            for label in order:
                command = [
                    sys.executable, "-B", Path(__file__).with_name("run.py"), "--provider", "ladybug",
                    "--fixture", args.fixture, "--extension", artifacts[label], "--library", args.library,
                    "--runs", "4", "--block", str(block),
                ]
                completed = subprocess.run(command, input=request, text=True, capture_output=True, check=True)
                workers.append({"release": label, **json.loads(completed.stdout)})
    summary = {}
    for case in CASES:
        summary[case] = {}
        for label in artifacts:
            values = sorted(s["wall_ms"] for w in workers if w["release"] == label
                            for s in w["samples"] if s["case"] == case)
            if len(values) != 16:
                raise ValueError(f"Missing observations for {label} {case}")
            summary[case][label] = {"n": len(values), "p50_ms": median(values),
                                    "p95_ms": values[math.ceil(.95 * len(values)) - 1]}
    result = {
        "provider": "ladybug",
        "isolated": args.isolated,
        "fixture": json.loads((args.fixture / "fixture.json").read_text()),
        "library_sha256": digest(args.library),
        "extension_sha256": {label: digest(path) for label, path in artifacts.items()},
        "expected": reference["expected"],
        "cases": CASES,
        "workers": workers,
        "summary": summary,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
