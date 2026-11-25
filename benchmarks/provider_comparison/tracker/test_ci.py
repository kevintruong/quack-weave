"""Exercise the Actions range, gate and history writer with real temporary Git refs."""
from contextlib import chdir, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import archive
import ci


HERE = Path(__file__).resolve().parent


def git(*args, cwd=None):
    return subprocess.check_output(["git", *args], text=True, cwd=cwd, stderr=subprocess.PIPE).strip()


def init_repo(path):
    git("init", "-q", "-b", "main", str(path))
    git("config", "user.name", "Tracker test", cwd=path)
    git("config", "user.email", "tracker@example.invalid", cwd=path)


def commit(label):
    git("commit", "--allow-empty", "-qm", label)
    return git("rev-parse", "HEAD")


def pack(entries):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, obj in entries.items():
            bundle.writestr(name, json.dumps(obj))
    return data.getvalue()


def evidence(sha, status, snapshot=None, event="main", run=100, attempt=1):
    entries = {f"{sha}/record.json": {"commit": sha, "status": status}}
    if snapshot is not None:
        entries[f"{sha}/snapshot.json"] = snapshot
    return dict(archive.records(pack(entries), event, run, attempt, sha))


class TrackerCI(unittest.TestCase):
    def test_pr_and_push_include_each_introduced_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_repo(tmp)
            with chdir(tmp):
                main = commit("main")
                old = commit("one")
                two = commit("two")
                head = commit("three")
                pr = {"pull_request": {"head": {"sha": head}, "base": {"sha": main}}}
                self.assertEqual(ci.commits("pull_request", pr), [old, two, head])
                self.assertEqual(ci.commits("pull_request", {**pr, "before": old}), [two, head])
                self.assertEqual(ci.commits("push", {"before": old, "after": head}), [two, head])
                self.assertEqual(ci.commits("push", {"before": head, "after": head}), [head])
                with self.assertRaises(ValueError):
                    ci.commits("push", {"after": "HEAD"})
                git("checkout", "-q", "-b", "replacement", main)
                new = commit("force push")
                self.assertEqual(ci.commits("push", {"before": head, "after": new}), [new])
                missing = "f" * 40
                git("remote", "add", "origin", Path(tmp).as_uri())
                pr["pull_request"]["head"]["sha"] = new
                self.assertEqual(ci.commits("pull_request", {**pr, "before": missing}), [new])

    def test_sharding_keeps_order_and_all_commits(self):
        shas = [f"{n:040x}" for n in range(650)]
        chunks = ci.matrix(shas)["include"]
        self.assertLessEqual(len(chunks), 32)
        self.assertEqual([s for x in chunks for s in x["commits"].split()], shas)
        self.assertEqual([x["index"] for x in chunks], list(range(len(chunks))))

    def test_verified_timings_are_advisory_per_percentile(self):
        row = {"provider": "relate", "route": "qw_pgq", "case": "view", "p50_ms": 0.1, "p95_ms": 0.2}
        past = {"workspace_head": "c" * 40, "summary": [row]}
        self.assertEqual(ci.judge(past, None)["status"], "baseline")
        # A 0.01 ms increase from 0.1 ms is exactly 10%.
        fixtures = []
        for p50, p95, regressions, improvements in [
            (0.1, 0.2, [], []), (0.109999, 0.219999, [], []),
            (0.11, 0.2, ["p50"], []), (0.099, 0.22, ["p95"], ["p50"]),
            (0.12, 0.24, ["p50", "p95"], []), (0.09, 0.18, [], ["p50", "p95"]),
        ]:
            with self.subTest(p50=p50, p95=p95):
                current = {"summary": [{**row, "p50_ms": p50, "p95_ms": p95}]}
                decision = ci.judge(current, past)
                fixtures.append(decision)
                self.assertEqual(decision["status"], "passed")
                self.assertEqual(decision["baseline_sha"], past["workspace_head"])
                for key, expected in [("regressions", regressions), ("improvements", improvements)]:
                    self.assertEqual([m for series in decision[key] for m in series["metrics"]], expected)
        for bad in [0, -1, float("nan"), float("inf")]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ci.judge({"summary": [{**row, "p50_ms": bad}]}, past)
        if runner := os.environ.get("DUCKDB_UNITTEST"):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "records.json"
                path.write_text(json.dumps(fixtures))
                check = subprocess.run(
                    [runner, "--test-dir", tmp, "--env-passthrough", "QW_ADVISORY_FIXTURE", "--stdin"],
                    input=(HERE / "advisory.test").read_text(), text=True, capture_output=True,
                    env={**os.environ, "QW_ADVISORY_FIXTURE": str(path)})
                self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
                self.assertRegex(check.stdout, r"All tests passed \([1-9][0-9]* assertions? in 1 test case\)")

    def test_judge_displays_and_archives_the_same_tables_on_regression(self):
        previous = json.loads((HERE / "sf1.json").read_text())
        previous["pair_id"] = "one-job"
        selection = {"baseline_sha": previous["workspace_head"], "artifact_id": "17",
                     "extension_sha256": previous["binaries"]["extension"]}
        current = deepcopy(previous)
        sha = "b" * 40
        current["workspace_head"] = sha
        current["id"] = "candidate-run"
        slow = next(r for r in current["summary"] if r["case"] == "full_scan_aggregate")
        slow.update(p50_ms=slow["p50_ms"] * 2, p95_ms=slow["p95_ms"] * 2)
        for metric in ("p50_ms", "p95_ms"):
            current["summary"][1][metric] *= 0.5
        current["summary"][0]["p50_ms"] *= 1.05
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / sha
            folder.mkdir()
            summary = Path(tmp) / "summary.md"
            (folder / "snapshot.json").write_text(json.dumps(current))
            (folder / "baseline.json").write_text(json.dumps(previous))
            selected = Path(tmp) / "selection.json"
            selected.write_text(json.dumps(selection))
            env = {k: "fixture" for k in ("QW_RUNNER_CLASS", "QW_CPU", "QW_CORES", "QW_MEMORY")}
            env.update(GITHUB_STEP_SUMMARY=str(summary), HOST_ARTIFACT_ID="20",
                       QW_DUCKDB_ARCHIVE_SHA256="d"*64, QW_RELEASE_ARTIFACT_ID="21", GITHUB_ACTIONS="true")
            with (patch.dict(os.environ, env, clear=True),
                  patch.object(sys, "argv", ["ci.py", "judge", str(folder), "--selection", str(selected)]),
                  redirect_stdout(io.StringIO()) as log):
                selected.write_text(json.dumps({**selection, "extension_sha256": "0" * 64}))
                with self.assertRaisesRegex(ValueError, "Wrong baseline release"):
                    ci.main()
                self.assertFalse((folder / "record.json").exists())
                selected.write_text(json.dumps(selection))
                self.assertEqual(ci.main(), 0)
                self.assertIn("::warning::", log.getvalue())
            report = summary.read_text()
            self.assertIn("same runner", report)
            self.assertEqual(report.count("Baseline p50 (ms)"), 2)
            self.assertIn("| Provider | Route | Workload | Samples |", report)
            self.assertIn("**+100.0% regression**", report)
            self.assertIn("**-50.0% faster**", report)
            self.assertIn("+5.0% acceptable", report)
            self.assertIn("0.0% unchanged", report)
            self.assertIn("600 warm samples", report)
            for r in current["summary"]:
                self.assertEqual(report.count(f"| {r['provider']} | {r['route']} | {r['case']} | {r['n']} |"), 1)
            record = json.loads((folder / "record.json").read_text())
            base = f"main/{sha}/100-1/"
            self.assertFalse((folder / "baseline.json").exists())
            names = ("record.json", "snapshot.json")
            entries = {f"{sha}/{name}": json.loads((folder / name).read_text()) for name in names}
            files = dict(archive.records(pack(entries), "main", 100, 1, sha))
            self.assertIn(base + "baseline.json", files)
            for wrong in ("host_id", "pair_id", "tracker_sha256", "workspace_head", "binaries"):
                corrupt = deepcopy(entries)
                corrupt[f"{sha}/snapshot.json"]["paired_baseline_snapshot"][wrong] = (
                    {"extension": "0"*64} if wrong == "binaries" else "other")
                with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                    list(archive.records(pack(corrupt), "main", 100, 1, sha))
            del entries[f"{sha}/snapshot.json"]["paired_baseline_snapshot"]
            with self.assertRaises(ValueError):
                list(archive.records(pack(entries), "main", 100, 1, sha))
            archive.add_reports(files)
            self.assertEqual(files[base + "README.md"].decode(), report)
            output = subprocess.check_output([sys.executable, HERE / "ci.py", "report", folder], text=True)
            self.assertEqual(output, report)

    def test_no_replayable_release_seeds_without_a_cross_host_verdict(self):
        old = json.loads((HERE / "sf1.json").read_text())
        with tempfile.TemporaryDirectory() as tmp, patch.object(ci, "compatible_baselines", return_value=[old]):
            selection = ci.select_pair(old, "a"*40, Path(tmp))
        self.assertEqual(selection, {"unavailable_sha": old["workspace_head"]})
        record = {"commit": old["workspace_head"], **ci.judge(old, None), **selection}
        self.assertIn("artifact unavailable", ci.markdown_report(record, old))

    def test_expired_nearest_release_uses_the_next_retained_attempt(self):
        sample = json.loads((HERE / "sf1.json").read_text())
        attempts = [{**sample, "actions_artifacts": {"release": artifact}} for artifact in ("1", "2")]
        with (tempfile.TemporaryDirectory() as tmp,
              patch.object(ci, "compatible_baselines", return_value=attempts),
              patch("artifacts.restore_previous", side_effect=[None, Path(tmp)/"release"])):
            selected = ci.select_pair(sample, None, Path(tmp))
        self.assertEqual(selected["artifact_id"], "2")

    def test_reports_show_seed_and_missing_measurements(self):
        sample = json.loads((HERE / "sf1.json").read_text())
        sha = sample["workspace_head"]
        seed = {"commit": sha, **ci.judge(sample, None)}
        self.assertIn("First compatible baseline", ci.markdown_report(seed, sample))
        for status in ("failed", "not_measured"):
            output = ci.markdown_report({"commit": sha, "status": status}, None)
            self.assertIn(status, output)
            self.assertNotIn("| Provider |", output)
        sample["summary"][0]["case"] = "[link](https://example.org)"
        with self.assertRaises(ValueError):
            ci.markdown_report(seed, sample)

    def test_historical_regression_keeps_its_recorded_verdict(self):
        sample = json.loads((HERE / "sf1.json").read_text())
        old = {"commit": sample["workspace_head"], "status": "regression",
               "thresholds": {"percent": 20, "floor_ms": 0.25},
               "regressions": [{"series": "relate/qw_pgq/view", "old_p50_ms": 1,
                                "new_p50_ms": 2, "old_p95_ms": 3, "new_p95_ms": 6}]}
        report = ci.markdown_report(old, sample)
        self.assertIn("· regression", report)
        self.assertIn("20%", report)
        self.assertNotIn("advisory", report)

    def test_rejects_misnamed_or_inconsistent_evidence(self):
        sha = "a" * 40
        record = {"commit": sha, "status": "passed"}
        valid = {f"{sha}/record.json": record, f"{sha}/snapshot.json": {"workspace_head": sha}}
        for bad in [{}, {f"{sha}/record.json": record}, {**valid, "../main/a": {}},
                    {**valid, f"{sha}/snapshot.json": {"workspace_head": "b" * 40}},
                    {**valid, f"{sha}/record.json": {**record, "status": "failed"}},
                    {**valid, f"{sha}/record.json": {**record, "extra": "a" * 4_000_000}}]:
            with self.assertRaises(ValueError):
                list(archive.records(pack(bad), "pull_request", 33, 1, sha))
        stored = evidence(sha, "not_measured", event="pull_request", run=33)
        record = json.loads(stored[f"pull_request/{sha}/33-1/record.json"])
        self.assertEqual((record["run_id"], record["head_sha"]), (33, sha))

    def test_missing_shard_retains_a_status_for_every_planned_commit(self):
        one, two = "a" * 40, "b" * 40
        expected = archive.planned_commits(pack({"commits.json": [one, two]}))
        files = evidence(one, "failed", event="pull_request", run=91)
        archive.complete_evidence(expected, files, "pull_request", 91, 1, two)
        self.assertEqual(json.loads(files[f"pull_request/{one}/91-1/record.json"])["status"], "failed")
        self.assertEqual(json.loads(files[f"pull_request/{two}/91-1/record.json"])["status"], "not_measured")
        with self.assertRaises(ValueError):
            archive.complete_evidence({two}, files, "pull_request", 91, 1, two)
        for bad in ([], [one, one], ["HEAD"]):
            with self.assertRaises(ValueError):
                archive.planned_commits(pack({"commits.json": bad}))

    def test_archive_replay_regression_and_compatible_ancestor(self):
        sample = json.loads((HERE / "sf1.json").read_text())
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "work"
            init_repo(repo)
            remote = Path(tmp, "history.git").as_uri()
            git("init", "--bare", "-q", str(Path(tmp, "history.git")))
            with chdir(repo):
                base = commit("base")
                tip = commit("tip")
                sample["workspace_head"] = base
                sample["ci_runner"] = {"cpu": "test"}
                first = evidence(base, "baseline", sample)
                archive.append(first, remote)
                ref = git("ls-remote", remote, archive.REF)
                archive.append(first, remote)
                self.assertEqual(git("ls-remote", remote, archive.REF), ref)
                with self.assertRaisesRegex(ValueError, "replace"):
                    archive.append({next(iter(first)): b"changed"}, remote)
                candidate = deepcopy(sample)
                candidate["workspace_head"] = tip
                archive.append(evidence(tip, "passed", candidate, event="pull_request"), remote)
                archive.append(evidence(tip, "regression", candidate, attempt=2), remote)
                other = {**candidate, "ci_runner": {"cpu": "different"}}
                archive.append(evidence(tip, "baseline", other, attempt=3), remote)
                git("fetch", "-q", remote, f"{archive.REF}:{ci.HISTORY}")
                self.assertIsNone(next(ci.compatible_baselines(sample, base), None))
                candidate["fixture"]["files"]["social.rl"]["sha256"] = "regenerated"
                self.assertEqual(next(ci.compatible_baselines(candidate, tip), None)["workspace_head"], base)
                for field in ("versions", "ci_runner"):
                    self.assertIsNone(next(ci.compatible_baselines({**candidate, field: {}}, tip), None))
                candidate["fixture"]["files"]["edges.csv"]["sha256"] = "different logical input"
                self.assertIsNone(next(ci.compatible_baselines(candidate, tip), None))

    def test_latest_main_table_survives_late_publication_and_pr_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, remote = Path(tmp, "work"), Path(tmp, "history.git")
            init_repo(repo)
            git("init", "--bare", "-q", str(remote))
            with chdir(repo):
                def publish(event, run, attempt, sha):
                    files = evidence(sha, "failed", event=event, run=run, attempt=attempt)
                    archive.add_reports(files)
                    archive.append(files, remote.as_uri(), main_report=(
                        f"main/{sha}/{run}-{attempt}/README.md" if event == "main" else None))

                publish("main", 100, 1, "a" * 40)
                publish("main", 100, 2, "a" * 40)
                publish("main", 99, 3, "b" * 40)
                publish("pull_request", 101, 1, "c" * 40)
                latest = git("show", f"{archive.REF}:README.md", cwd=remote)
                self.assertIn(f"main/{'a' * 40}/100-2/", latest)
                self.assertIn("No verified timing snapshot", latest)
                self.assertNotIn("99-3", latest)
                self.assertNotIn("101-1", latest)

    def test_concurrent_writers_keep_both_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            remote = Path(tmp, "remote.git")
            git("init", "--bare", "-q", str(remote))
            procs = []
            for attempt in (1, 2):
                work = Path(tmp, f"work-{attempt}")
                init_repo(work)
                name = f"main/{'a' * 40}/10-{attempt}/record.json"
                procs.append(subprocess.Popen(
                    [sys.executable, "-B", "-c",
                     "import archive,sys; archive.append({sys.argv[1]: b'{}'}, sys.argv[2])",
                     name, remote.as_uri()], cwd=work, env={**os.environ, "PYTHONPATH": str(HERE)},
                    stderr=subprocess.PIPE, text=True))
            for proc in procs:
                _, err = proc.communicate(timeout=60)
                self.assertEqual(proc.returncode, 0, err)
            names = git("ls-tree", "-r", "--name-only", archive.REF, cwd=remote).splitlines()
            self.assertEqual(len(names), 2)
            self.assertEqual(git("rev-list", "--count", archive.REF, cwd=remote), "2")

    def test_publisher_reads_planned_and_partial_artifacts_from_workflow_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp, "work")
            init_repo(repo)
            remote = Path(tmp, "origin.git")
            git("init", "--bare", "-q", str(remote))
            with chdir(repo):
                first = commit("first")
                head = commit("second")
                git("remote", "add", "origin", remote.as_uri())
                git("push", "-q", "origin", "main")
                payload = {"workflow_run": {"event": "push", "id": 90, "run_attempt": 2,
                           "path": ".github/workflows/CI.yml", "head_sha": head,
                           "head_branch": "main", "head_repository": {"id": 7}}, "repository": {"id": 7}}
                Path("event.json").write_text(json.dumps(payload))
                environment = {"GITHUB_EVENT_PATH": "event.json", "GITHUB_REPOSITORY": "owner/repo"}
                artifacts = [dict(name=name, id=i, expired=False, size_in_bytes=500)
                             for i, name in enumerate(("qw-plan-90-1", "qw-benchmark-90-1-0",
                                                       "qw-benchmark-90-2-1", "qw-native-tip-2"))]
                real_output = subprocess.check_output
                def github_or_git(cmd, **kwargs):
                    if cmd[0] != "gh":
                        return real_output(cmd, **kwargs)
                    if "--paginate" in cmd:
                        return json.dumps([{"artifacts": artifacts}]).encode()
                    if cmd[-1].endswith("/0/zip"):
                        return pack({"commits.json": [first, head]})
                    self.assertTrue(cmd[-1].endswith("/2/zip"))
                    sample = json.loads((HERE / "sf1.json").read_text())
                    sample["workspace_head"] = head
                    return pack({f"{head}/record.json": {"commit": head, "status": "baseline"},
                                 f"{head}/snapshot.json": sample})
                with patch.dict(os.environ, environment), patch.object(subprocess, "check_output", github_or_git):
                    archive.main()
                for sha, status in ((first, "not_measured"), (head, "baseline")):
                    key = f"{archive.REF}:main/{sha}/90-2/record.json"
                    self.assertEqual(json.loads(git("show", key, cwd=remote))["status"], status)
                self.assertIn("30 series", git("show", f"{archive.REF}:README.md", cwd=remote))


if __name__ == "__main__":
    unittest.main()
