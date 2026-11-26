import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import artifacts
from test_ci import git, init_repo


class NativeRelease(unittest.TestCase):
    def test_consumer_requires_exact_revision_profile_and_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            init_repo(repo)
            git("commit", "-qm", "source", "--allow-empty", cwd=repo)
            sha = git("rev-parse", "HEAD", cwd=repo)
            package = repo / artifacts.PACKAGE
            package.mkdir(parents=True)
            (package / artifacts.EXTENSION).write_bytes(b"release")
            (package / "licenses").mkdir()
            (package / "licenses" / "Relate-LICENSE").write_text("notice")
            output = Path(temp) / "outputs"
            artifacts.stage(repo, output)
            folder = output / sha
            artifacts.verify(folder, sha)
            with self.assertRaises(ValueError):
                artifacts.verify(folder, "a" * 40)
            manifest = folder / "manifest.json"
            saved = manifest.read_text()
            manifest.write_text(saved.replace(artifacts.PROFILE, "gql-only"))
            with self.assertRaises(ValueError):
                artifacts.verify(folder, sha)
            manifest.write_text(saved)
            (folder / artifacts.EXTENSION).write_bytes(b"other")
            with self.assertRaises(ValueError):
                artifacts.verify(folder, sha)

    def test_historical_shard_skips_head_and_preserves_good_sibling_on_failure(self):
        here = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp, "repo")
            init_repo(repo)

            def revision(name):
                git("add", "Makefile", cwd=repo)
                git("commit", "-qm", name, "--allow-empty", cwd=repo)
                return git("rev-parse", "HEAD", cwd=repo)

            makefile = repo / "Makefile"
            makefile.write_text("mvp2-deps:\n\t@true\nmvp2-relate-release:\n\t@false\n")
            bad = revision("no release")
            legacy_package = Path("build/mvp2-relate/release/extension/quack_weave")
            makefile.write_text(
                "mvp2-deps:\n\t@true\nmvp2-relate-release:\n"
                f"\tmkdir -p {legacy_package}/licenses\n"
                f"\tgit rev-parse HEAD > {legacy_package}/{artifacts.EXTENSION}\n"
                f"\ttouch {legacy_package}/licenses/Relate-LICENSE\n")
            legacy = revision("historical release")
            makefile.write_text(
                "native-deps:\n\t@true\nnative-release:\n"
                f"\tmkdir -p {artifacts.PACKAGE}/licenses\n"
                f"\tgit rev-parse HEAD > {artifacts.PACKAGE}/{artifacts.EXTENSION}\n"
                f"\ttouch {artifacts.PACKAGE}/licenses/Relate-LICENSE\n")
            good = revision("valid release")
            head = revision("event head")
            control = repo / "benchmarks/provider_comparison/tracker"
            control.mkdir(parents=True)
            for name in ("artifacts.py", "ci.py"):
                shutil.copy2(here / name, control)
            (repo / "build/deps").mkdir(parents=True)
            result = subprocess.run(["bash", here / "build_releases.sh", bad, good, legacy, head], cwd=repo,
                                    env={**os.environ, "SOURCE_HEAD": head, "RUNNER_TEMP": tmp},
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            releases = repo / "build/historical"
            self.assertEqual({p.name for p in releases.iterdir()}, {good, legacy})
            for sha in (good, legacy):
                artifacts.verify(releases / sha, sha)
                self.assertEqual((releases / sha / artifacts.EXTENSION).read_text().strip(), sha)


class RestoredRelease(unittest.TestCase):
    sha = "a" * 40
    blob = b"compiled combined extension"
    digest = hashlib.sha256(blob).hexdigest()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "scratch"
        self.snapshot = {"workspace_head": self.sha, "actions_artifacts": {"release": "42"},
                         "binaries": {"extension": self.digest}}
        self.manifest = {"commit": self.sha, "profile": artifacts.PROFILE, "sha256": self.digest}
        self.endpoint = "repos/sample/graphs/actions/artifacts/42"
        self.enterContext(patch.dict(os.environ, GITHUB_REPOSITORY="sample/graphs"))

    def archive(self, folders, *, data=None, manifest=None):
        body = io.BytesIO()
        with zipfile.ZipFile(body, "w") as archive:
            archive.writestr("../escape", b"unrelated")
            for folder in folders:
                archive.writestr(folder + "/manifest.json", json.dumps(self.manifest if manifest is None else manifest))
                archive.writestr(folder + "/" + artifacts.EXTENSION, self.blob if data is None else data)
        return body.getvalue()

    def github(self, body=b"", *, expired=False, failure=None, message=""):
        def request(cmd, *, stdout, stderr):
            self.assertEqual(cmd[:2], ["gh", "api"])
            self.assertIn(cmd[2], (self.endpoint, self.endpoint + "/zip"))
            if cmd[2] == failure:
                return subprocess.CompletedProcess(cmd, 1, stderr=message.encode())
            if cmd[2] == self.endpoint:
                stdout.write(json.dumps({"id": 42, "expired": expired}).encode())
            else:
                self.assertFalse(expired)
                stdout.write(body)
            return subprocess.CompletedProcess(cmd, 0, stderr=b"")
        return patch.object(subprocess, "run", side_effect=request)

    def test_restores_only_recorded_release_from_both_archive_layouts(self):
        for prefix in ["releases/", ""]:
            with self.subTest(prefix=prefix), self.github(self.archive([prefix + self.sha])):
                path = artifacts.restore_previous(self.snapshot, self.folder)
                self.assertEqual(path.name, artifacts.EXTENSION)
                self.assertEqual(path.read_bytes(), self.blob)
                self.assertFalse(list(Path(self.tmp.name).rglob("escape")))

    def test_rejects_wrong_commit_profile_digest_bytes_or_layout(self):
        bad = "f" * 64
        for body in [self.archive([self.sha], manifest={**self.manifest, "commit": "b" * 40}),
                     self.archive([self.sha], manifest={**self.manifest, "profile": "other"}),
                     self.archive([self.sha], manifest={**self.manifest, "sha256": bad}),
                     self.archive([self.sha], data=b"changed"),
                     self.archive(["unknown-layout/" + self.sha]),
                     self.archive([self.sha, "releases/" + self.sha])]:
            with self.github(body), self.assertRaises(ValueError):
                artifacts.restore_previous(self.snapshot, self.folder)
        self.snapshot["binaries"]["extension"] = bad
        with self.github(self.archive([self.sha])), self.assertRaises(ValueError):
            artifacts.restore_previous(self.snapshot, self.folder)
        self.assertFalse(list(self.folder.rglob(artifacts.EXTENSION)))

    def test_distinguishes_missing_expired_and_unavailable_from_broken_requests(self):
        with self.github(expired=True):
            self.assertIsNone(artifacts.restore_previous(self.snapshot, self.folder))
        for endpoint in (self.endpoint, self.endpoint + "/zip"):
            for status in [404, 410]:
                with self.github(failure=endpoint, message=f"gh: unavailable (HTTP {status})\n"):
                    self.assertIsNone(artifacts.restore_previous(self.snapshot, self.folder))
            for message in ["gh: Forbidden (HTTP 403)", "gh: bad credentials (HTTP 401)", "network timeout"]:
                with self.github(failure=endpoint, message=message), self.assertRaises(RuntimeError):
                    artifacts.restore_previous(self.snapshot, self.folder)
        with patch.object(subprocess, "run") as request:
            self.snapshot.pop("actions_artifacts")
            self.assertIsNone(artifacts.restore_previous(self.snapshot, self.folder))
            for value in ["42/zip", -1, True]:
                self.snapshot["actions_artifacts"] = {"release": value}
                with self.assertRaises(ValueError):
                    artifacts.restore_previous(self.snapshot, self.folder)
            request.assert_not_called()
