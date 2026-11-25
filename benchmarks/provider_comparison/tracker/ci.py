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


def compatible_baselines(current, start):
    tree = f"{HISTORY}:main"
    if not start or subprocess.run(["git", "cat-file", "-e", tree], capture_output=True).returncode:
        return
    recorded = set(git("ls-tree", "--name-only", tree).splitlines())
    for ancestor in git("rev-list", "--first-parent", checked_sha(start)).splitlines():
        if ancestor not in recorded or ancestor == current["workspace_head"]:
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
                yield snapshot


def select_pair(current, ancestor, directory):
    from artifacts import restore_previous

    unavailable = {}
    for previous in compatible_baselines(current, ancestor):
        sha = checked_sha(previous["workspace_head"])
        extension = restore_previous(previous, directory)
        if extension is not None:
            return {"baseline_sha": sha, "artifact_id": previous["actions_artifacts"]["release"],
                    "extension_sha256": previous["binaries"]["extension"], "extension": str(extension)}
        unavailable.setdefault("unavailable_sha", sha)
    return unavailable


def annotate(snapshot, release_id):
    snapshot["ci_runner"] = {k: os.environ[k] for k in ("QW_RUNNER_CLASS", "QW_CPU", "QW_CORES", "QW_MEMORY")}
    if "QW_BUILD_TOOLCHAIN" in os.environ:
        snapshot["ci_runner"]["QW_BUILD_TOOLCHAIN"] = os.environ["QW_BUILD_TOOLCHAIN"]
    if release_id:
        snapshot["upstream_duckdb_sha256"] = os.environ["QW_DUCKDB_ARCHIVE_SHA256"]
        snapshot["actions_artifacts"] = {"release": release_id, "duckdb_host": os.environ["HOST_ARTIFACT_ID"]}


def verify_pair(current, previous, selection):
    if (previous["workspace_head"] != selection["baseline_sha"]
            or current["workspace_head"] == previous["workspace_head"]
            or previous["binaries"]["extension"] != selection["extension_sha256"]
            or previous["actions_artifacts"]["release"] != selection["artifact_id"]):
        raise ValueError("Wrong baseline release for paired measurement")
    for key in ("host_id", "pair_id", "tracker_sha256", "fixture"):
        if not current.get(key) or current[key] != previous.get(key):
            raise ValueError(f"Paired measurements require matching {key}")
    def clients(snapshot):
        return {k: v for k, v in snapshot["binaries"].items() if k != "extension"}
    if (current["id"] == previous["id"] or clients(current) != clients(previous)
            or cohort(current) != cohort(previous) or series(current).keys() != series(previous).keys()):
        raise ValueError("Incompatible paired measurements")


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


def report_label(value):
    # History can include fork PRs. Render plain identifiers from the evidence.
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_./ -]+", value):
        raise ValueError("Invalid benchmark report label")
    return value


def markdown_report(record, snapshot, baseline=None):
    sha = checked_sha(record["commit"])
    status = record["status"]
    if status not in RESULTS:
        raise ValueError("Unknown benchmark status")
    lines = [f"### Benchmark `{sha[:12]}` · {status}", ""]
    if status in {"failed", "not_measured"}:
        return "\n".join([*lines, "No verified timing snapshot is available.", ""])
    if not isinstance(snapshot, dict) or snapshot["workspace_head"] != sha:
        raise ValueError("Snapshot identifies a different source commit")
    rows = snapshot["summary"]
    if any(r["scope"] not in {"standalone", "hybrid"} for r in rows):
        raise ValueError("Unknown benchmark scope")
    environment = snapshot.get("ci_runner", {})
    if not isinstance(environment, dict):
        raise ValueError("Invalid runner metadata")
    runner = report_label(environment.get("QW_RUNNER_CLASS", snapshot["machine"]))
    lines.extend([f"{runner} · protocol {snapshot['protocol']:d} · {snapshot['edge_count']:,d} edges · "
                  f"{len(rows)} series · {sum(r['n'] for r in rows):,d} warm samples.", ""])
    if record.get("paired_baseline"):
        lines.extend([f"Compared with main commit `{checked_sha(record['baseline_sha'])[:12]}` on the same runner. "
                      "The two releases alternated order across measurement blocks.", ""])
    elif record.get("unavailable_sha"):
        lines.extend([f"Baseline artifact unavailable for `{checked_sha(record['unavailable_sha'])[:12]}`. "
                      "Recorded a new baseline without a latency verdict.", ""])
    elif record.get("baseline_sha"):
        lines.extend([f"Compared with main commit `{checked_sha(record['baseline_sha'])[:12]}`.", ""])
    elif status == "baseline":
        lines.extend(["First compatible baseline for this runner and protocol.", ""])
    if "thresholds" in record:
        thresholds = record["thresholds"]
        lines.extend([f"The gate flags a series when p50 and p95 both rise by at least {thresholds['percent']:g}% "
                      f"and p50 increases by at least {thresholds['floor_ms']:g} ms.", ""])

    regressions = record.get("regressions", [])
    if regressions:
        lines.extend(["#### Slower than baseline", "",
                      "| Series | Prior p50 (ms) | Current p50 (ms) | Change | Prior p95 (ms) | Current p95 (ms) | Change |",
                      "|---|---:|---:|---:|---:|---:|---:|"])
        for r in regressions:
            old50, new50 = r["old_p50_ms"], r["new_p50_ms"]
            old95, new95 = r["old_p95_ms"], r["new_p95_ms"]
            lines.append(f"| {report_label(r['series'])} | {old50:,.3f} | {new50:,.3f} | {(new50/old50-1):+.1%} "
                         f"| {old95:,.3f} | {new95:,.3f} | {(new95/old95-1):+.1%} |")
        lines.append("")

    if baseline is None:
        baseline = snapshot.get("paired_baseline_snapshot")
    prior = series(baseline) if baseline else {}
    for scope, title in (("standalone", "Standalone graph queries"), ("hybrid", "Hybrid SQL and graph queries")):
        lines.extend([f"#### {title}", "",
                      "| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct |"
                      + (" Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |" if prior else ""),
                      "|---|---|---|---:|---:|---:|---:|" + ("---:|" * 4 if prior else "")])
        for row in rows:
            if row["scope"] == scope:
                keys = " | ".join(report_label(row[key]) for key in ("provider", "route", "case"))
                ratio = f"{row['qw_over_direct']:.2f}×" if row.get("qw_over_direct") is not None else "—"
                line = f"| {keys} | {row['n']:d} | {row['p50_ms']:,.3f} | {row['p95_ms']:,.3f} | {ratio} |"
                if prior:
                    old = prior[(row["provider"], row["route"], row["case"])]
                    for metric in ("p50_ms", "p95_ms"):
                        line += f" {old[metric]:,.3f} | {row[metric] / old[metric] - 1:+.1%} |"
                lines.append(line)
        lines.append("")
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--manifest", type=Path)
    init = sub.add_parser("init")
    init.add_argument("folder", type=Path)
    init.add_argument("commits", nargs="+")
    report = sub.add_parser("report", help="Render an archived commit attempt as Markdown")
    report.add_argument("folder", type=Path)
    select = sub.add_parser("select", help="Restore a compatible main release before starting the paired measurement")
    select.add_argument("description", type=Path)
    select.add_argument("selection", type=Path)
    select.add_argument("--ancestor")
    check = sub.add_parser("judge")
    check.add_argument("folder", type=Path)
    check.add_argument("--selection", type=Path, required=True)
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
    elif args.cmd == "report":
        record = json.loads((args.folder / "record.json").read_text())
        path = args.folder / "snapshot.json"
        baseline = args.folder / "baseline.json"
        print(markdown_report(record, json.loads(path.read_text()) if path.exists() else None,
                              json.loads(baseline.read_text()) if baseline.exists() else None), end="")
    elif args.cmd == "select":
        description = json.loads(args.description.read_text())
        annotate(description, os.environ.get("QW_RELEASE_ARTIFACT_ID"))
        selection = select_pair(description, args.ancestor, args.selection.parent)
        args.selection.write_text(json.dumps(selection) + "\n")
    else:
        sha = checked_sha(args.folder.name)
        snapshot_file = args.folder / "snapshot.json"
        snapshot = json.loads(snapshot_file.read_text())
        if snapshot["workspace_head"] != sha:
            raise ValueError("Snapshot identifies a different source commit")
        annotate(snapshot, os.environ.get("QW_RELEASE_ARTIFACT_ID"))
        selection = json.loads(args.selection.read_text())
        baseline_file = args.folder / "baseline.json"
        previous = None
        if selection.get("baseline_sha"):
            previous = json.loads(baseline_file.read_text())
            annotate(previous, selection["artifact_id"])
            verify_pair(snapshot, previous, selection)
            # Older history publishers accept only record.json and snapshot.json in Actions artifacts.
            snapshot["paired_baseline_snapshot"] = previous
        elif "pair_id" in snapshot or baseline_file.exists():
            raise ValueError("Unexpected paired snapshot for an unpaired measurement")
        result = judge(snapshot, previous,
                       float(os.environ.get("QW_REGRESSION_PERCENT") or 20),
                       float(os.environ.get("QW_REGRESSION_FLOOR_MS") or 0.25))
        record = {"commit": sha, **result}
        if previous:
            record["paired_baseline"] = {k: selection[k] for k in ("artifact_id", "extension_sha256")}
        elif "unavailable_sha" in selection:
            record["unavailable_sha"] = checked_sha(selection["unavailable_sha"])
        snapshot_file.write_text(json.dumps(snapshot, indent=2, allow_nan=False) + "\n")
        if previous:
            baseline_file.unlink()
        (args.folder / "record.json").write_text(json.dumps(record, indent=2) + "\n")
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
            summary.write(markdown_report(record, snapshot))
        return int(result["status"] == "regression")


if __name__ == "__main__":
    raise SystemExit(main())
