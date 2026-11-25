"""Append inert JSON from one completed Actions run to the benchmark-history ref."""
import io
import json
import os
from pathlib import Path
import random
import re
import subprocess
import tempfile
import time
import zipfile

from ci import RESULTS, checked_sha


REF = "refs/heads/benchmark-history"


def planned_commits(body):
    with zipfile.ZipFile(io.BytesIO(body)) as bundle:
        if bundle.namelist() != ["commits.json"] or bundle.getinfo("commits.json").file_size > 1_000_000:
            raise ValueError("Invalid commit manifest")
        shas = json.loads(bundle.read("commits.json"))
        if not isinstance(shas, list) or not shas:
            raise ValueError("Expected a nonempty commit list")
        expected = {checked_sha(sha) for sha in shas}
        if len(expected) != len(shas):
            raise ValueError("Duplicate planned commit")
        return expected


def records(archive, event, run_id, attempt, head):
    grouped = {}
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        if sum(item.file_size for item in bundle.infolist()) > 128_000_000:
            raise ValueError("Oversized unpacked benchmark artifact")
        for item in bundle.infolist():
            if item.is_dir():
                continue
            match = re.fullmatch(r"([a-f0-9]{40})/(record|snapshot)\.json", item.filename)
            if not match or item.file_size > 4_000_000:
                raise ValueError("Unexpected artifact member or size")
            sha, kind = match.groups()
            pair = grouped.setdefault(sha, {})
            if kind in pair:
                raise ValueError("Duplicate artifact member")
            pair[kind] = json.loads(bundle.read(item))
    if not grouped:
        raise ValueError("Empty benchmark artifact")
    for sha, pair in grouped.items():
        record = pair["record"]
        if record["commit"] != sha or record["status"] not in RESULTS:
            raise ValueError("Invalid benchmark status or identity")
        measured = record["status"] in {"baseline", "passed", "regression"}
        if measured != ("snapshot" in pair) or (measured and pair["snapshot"]["workspace_head"] != sha):
            raise ValueError("Benchmark snapshot and commit status disagree")
        record.update(event=event, run_id=run_id, run_attempt=attempt, head_sha=head)
        for kind, obj in pair.items():
            name = f"{event}/{sha}/{run_id}-{attempt}/{kind}.json"
            yield name, (json.dumps(obj, allow_nan=False, separators=(",", ":")) + "\n").encode()


def git(*args, data=None, env=None):
    return subprocess.check_output(["git", *args], input=data, env=env).strip()


def complete_evidence(expected, files, event, run_id, attempt, head):
    observed = {path.split("/")[1] for path in files}
    if observed - expected:
        raise ValueError("Benchmark reported commits outside the plan")
    for sha in expected - observed:
        record = {"commit": sha, "status": "not_measured", "event": event, "run_id": run_id,
                  "run_attempt": attempt, "head_sha": head}
        files[f"{event}/{sha}/{run_id}-{attempt}/record.json"] = (
            json.dumps(record, separators=(",", ":")) + "\n").encode()


def append(files, remote="origin"):
    # Separate indexes and ordinary fast-forward pushes preserve concurrent runs.
    # Nothing from an artifact is checked out, imported, or used as a Git ref.
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index"),
               "GIT_AUTHOR_NAME": "benchmark-history", "GIT_COMMITTER_NAME": "benchmark-history",
               "GIT_AUTHOR_EMAIL": "benchmark@users.noreply.github.com",
               "GIT_COMMITTER_EMAIL": "benchmark@users.noreply.github.com"}
        for retry in range(10):
            tip = None
            if git("ls-remote", "--heads", remote, REF):
                git("fetch", "--quiet", "--no-tags", "--depth=1", remote, REF)
                tip = git("rev-parse", "FETCH_HEAD").decode()
            git("read-tree", tip or "--empty", env=env)
            changed = False
            for name, content in files.items():
                blob = git("hash-object", "-w", "--stdin", data=content)
                previous = git("ls-files", "--stage", "--", name, env=env)
                if previous:
                    if previous.split()[1] != blob:
                        raise ValueError(f"Refusing to replace archived measurement {name}")
                    continue
                git("update-index", "--add", "--cacheinfo", "100644", blob.decode(), name, env=env)
                changed = True
            if not changed:
                return
            tree = git("write-tree", env=env).decode()
            commit = git("commit-tree", tree, *(["-p", tip] if tip else []),
                         "-m", "Append verified benchmark observations and run outcomes", env=env).decode()
            result = subprocess.run(["git", "push", remote, f"{commit}:{REF}"], capture_output=True)
            if result.returncode == 0:
                return
            if retry == 9:
                raise RuntimeError(result.stderr.decode())
            time.sleep(random.uniform(.1, min(6, 2 ** retry)))


def main():
    payload = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    run = payload["workflow_run"]
    event = run["event"]
    if run["path"] not in {".github/workflows/CI.yml", ".github/workflows/Benchmark.yml"}:
        raise ValueError("Unexpected source workflow path")
    if event not in {"push", "pull_request"} or (event == "push" and (
            run["head_branch"] != "main" or run["head_repository"]["id"] != payload["repository"]["id"])):
        raise ValueError("Unexpected source workflow event")
    run_id, attempt = int(run["id"]), int(run["run_attempt"])
    head = checked_sha(run["head_sha"])
    repo = os.environ["GITHUB_REPOSITORY"]
    pages = json.loads(subprocess.check_output([
        "gh", "api", "--paginate", "--slurp", f"repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100"]))
    artifacts = [a for page in pages for a in page["artifacts"]]
    def download(artifact):
        if artifact["expired"] or artifact["size_in_bytes"] > 100_000_000:
            raise ValueError("Expired or oversized benchmark artifact")
        return subprocess.check_output(["gh", "api", f"repos/{repo}/actions/artifacts/{int(artifact['id'])}/zip"])

    # A retry of only failed jobs reuses the most recent successful plan.
    plans = [(int(m[1]), a) for a in artifacts
             if (m := re.fullmatch(rf"qw-plan-{run_id}-([0-9]+)", a["name"])) and int(m[1]) <= attempt]
    if not plans:
        raise ValueError("Source run produced no commit manifest")
    expected = planned_commits(download(max(plans, key=lambda pair: pair[0])[1]))
    event = "main" if event == "push" else "pull_request"
    files = {}
    for artifact in artifacts:
        if not re.fullmatch(rf"qw-benchmark-{run_id}-{attempt}-[0-9]+", artifact["name"]):
            continue
        for name, content in records(download(artifact), event, run_id, attempt, head):
            if name in files:
                raise ValueError(f"Duplicate evidence across shards: {name}")
            files[name] = content
    complete_evidence(expected, files, event, run_id, attempt, head)
    # Restrict even fork artifacts to their triggering source history.
    git("fetch", "--quiet", "--no-tags", "origin", head)
    reachable = set(git("rev-list", head).decode().splitlines())
    if head not in expected or expected - reachable:
        raise ValueError("Commit manifest disagrees with the triggering source history")
    append(files)
    print(f"Archived {len(files)} files for run {run_id}, attempt {attempt}.")


if __name__ == "__main__":
    main()
