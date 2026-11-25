"""GitHub Actions commit selection, comparable ancestor lookup and latency gate."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys


HISTORY = "refs/remotes/origin/benchmark-history"
SHA = re.compile(r"[0-9a-f]{40}")
RESULTS = {"passed", "baseline", "regression", "not_measured", "failed"}


def git(*args, cwd=None):
    return subprocess.check_output(["git", *args], text=True, cwd=cwd).strip()


def checked_sha(value):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError("Invalid Git commit ID")
    return value


def commits(event, payload):
    if event == "pull_request":
        head = checked_sha(payload["pull_request"]["head"]["sha"])
        base = checked_sha(payload["pull_request"]["base"]["sha"])
    elif event == "workflow_dispatch":
        return [checked_sha(os.environ["GITHUB_SHA"])]
    elif event == "push":
        head, base = checked_sha(payload["after"]), None
    else:
        raise ValueError(f"Unsupported event {event}")
    before = payload.get("before")
    excludes = [base] if base else []
    if before and before != "0" * 40:
        before = checked_sha(before)
        available = subprocess.run(["git", "cat-file", "-e", before], capture_output=True).returncode == 0
        if not available:
            # GitHub may stop serving the previous tip after a force push.
            available = subprocess.run(["git", "fetch", "--no-tags", "origin", before], capture_output=True).returncode == 0
        if available:
            excludes.append(before)
        else:
            print(f"Previous tip {before} is unavailable. Measuring the full reachable range.", file=sys.stderr)
    selected = git("rev-list", "--reverse", "--topo-order", head,
                   *["^" + sha for sha in excludes]).splitlines()
    return selected or [head]


def matrix(shas):
    # Keep multi-commit pushes lossless within GitHub's 256-job matrix limit.
    width = max(1, math.ceil(len(shas) / 32))
    return {"include": [{"index": i // width, "commits": " ".join(shas[i:i + width])}
                        for i in range(0, len(shas), width)]}


def cohort(snapshot):
    # Hosted VMs have ephemeral hostnames. Compare a hardware/OS cohort and the
    # logical input, even if a freshly checkpointed provider file has a new ID.
    fixture = snapshot["fixture"]
    return [snapshot[k] for k in ("protocol", "platform", "machine", "duckdb_threads",
                                    "runs", "blocks", "watchlist", "expected", "statements", "versions")] + [
        snapshot.get("ci_runner"), snapshot.get("upstream_duckdb_sha256"), fixture["source_sha256"], fixture["selection"],
        fixture["files"]["edges.csv"]["sha256"], snapshot["edge_count"]]


def series(snapshot):
    return {(r["provider"], r["route"], r["case"]): r for r in snapshot["summary"]}


def find_baseline(current, start):
    tree = f"{HISTORY}:main"
    if not start or subprocess.run(["git", "cat-file", "-e", tree], capture_output=True).returncode:
        return None
    recorded = set(git("ls-tree", "--name-only", tree).splitlines())
    for ancestor in git("rev-list", "--first-parent", checked_sha(start)).splitlines():
        if ancestor not in recorded:
            continue
        folder = f"{tree}/{ancestor}"
        attempts = git("ls-tree", "--name-only", folder).splitlines()
        for entry in sorted(attempts, key=lambda s: tuple(map(int, s.split("-"))), reverse=True):
            record = json.loads(git("show", f"{folder}/{entry}/record.json"))
            if record["status"] not in {"passed", "baseline"}:
                continue
            snapshot = json.loads(git("show", f"{folder}/{entry}/snapshot.json"))
            if (snapshot["workspace_head"] == ancestor and cohort(current) == cohort(snapshot)
                    and series(current).keys() == series(snapshot).keys()):
                return snapshot
    return None


def judge(current, previous, percent, floor_ms):
    if not all(math.isfinite(x) and x > 0 for x in (percent, floor_ms)):
        raise ValueError("Latency thresholds must be positive finite numbers")
    thresholds = {"percent": percent, "floor_ms": floor_ms}
    if previous is None:
        return {"status": "baseline", "baseline_sha": None, "thresholds": thresholds, "regressions": []}
    old = series(previous)
    regressions = []
    for key, row in series(current).items():
        prior = old[key]
        delta = row["p50_ms"] - prior["p50_ms"]
        factor = 1 + percent / 100
        if (delta >= floor_ms and row["p50_ms"] >= prior["p50_ms"] * factor
                and row["p95_ms"] >= prior["p95_ms"] * factor):
            regressions.append({"series": "/".join(key), "old_p50_ms": prior["p50_ms"],
                                "new_p50_ms": row["p50_ms"], "old_p95_ms": prior["p95_ms"],
                                "new_p95_ms": row["p95_ms"]})
    return {"status": "regression" if regressions else "passed",
            "baseline_sha": previous["workspace_head"], "thresholds": thresholds, "regressions": regressions}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--manifest", type=Path)
    init = sub.add_parser("init")
    init.add_argument("folder", type=Path)
    init.add_argument("commits", nargs="+")
    check = sub.add_parser("judge")
    check.add_argument("folder", type=Path)
    check.add_argument("--ancestor")
    args = p.parse_args()
    if args.cmd == "plan":
        payload = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        shas = commits(os.environ["GITHUB_EVENT_NAME"], payload)
        if args.manifest:
            args.manifest.write_text(json.dumps(shas) + "\n")
        print(json.dumps(matrix(shas), separators=(",", ":")))
    elif args.cmd == "init":
        for sha in args.commits:
            folder = args.folder / checked_sha(sha)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "record.json").write_text(json.dumps({"commit": sha, "status": "not_measured"}) + "\n")
    else:
        sha = checked_sha(args.folder.name)
        snapshot_file = args.folder / "snapshot.json"
        snapshot = json.loads(snapshot_file.read_text())
        if snapshot["workspace_head"] != sha:
            raise ValueError("Snapshot identifies a different source commit")
        snapshot["ci_runner"] = {k: os.environ[k] for k in ("QW_RUNNER_CLASS", "QW_CPU", "QW_CORES", "QW_MEMORY")}
        if "QW_BUILD_TOOLCHAIN" in os.environ:
            snapshot["ci_runner"]["QW_BUILD_TOOLCHAIN"] = os.environ["QW_BUILD_TOOLCHAIN"]
        if os.environ.get("QW_RELEASE_ARTIFACT_ID"):
            snapshot["upstream_duckdb_sha256"] = os.environ["QW_DUCKDB_ARCHIVE_SHA256"]
            snapshot["actions_artifacts"] = {"release": os.environ["QW_RELEASE_ARTIFACT_ID"],
                                             "duckdb_host": os.environ["HOST_ARTIFACT_ID"]}
        snapshot_file.write_text(json.dumps(snapshot, indent=2, allow_nan=False) + "\n")
        result = judge(snapshot, find_baseline(snapshot, args.ancestor),
                       float(os.environ.get("QW_REGRESSION_PERCENT") or 20),
                       float(os.environ.get("QW_REGRESSION_FLOOR_MS") or 0.25))
        record = {"commit": sha, **result}
        (args.folder / "record.json").write_text(json.dumps(record, indent=2) + "\n")
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
            print(f"### Benchmark `{sha[:12]}` — {result['status']}", file=summary)
            print(f"\n{len(snapshot['summary'])} verified series. Compared with "
                  + (result["baseline_sha"] or "no compatible archived main ancestor (seed run)") + ".", file=summary)
            for r in result["regressions"]:
                print(f"\n- {r['series']} p50 {r['old_p50_ms']:.3f} → {r['new_p50_ms']:.3f} ms, "
                      f"p95 {r['old_p95_ms']:.3f} → {r['new_p95_ms']:.3f} ms", file=summary)
        return int(result["status"] == "regression")


if __name__ == "__main__":
    raise SystemExit(main())
