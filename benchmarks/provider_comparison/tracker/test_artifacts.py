import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

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
            makefile.write_text(
                "mvp2-deps:\n\t@true\nmvp2-relate-release:\n"
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
            result = subprocess.run(["bash", here / "build_releases.sh", bad, good, head], cwd=repo,
                                    env={**os.environ, "SOURCE_HEAD": head, "RUNNER_TEMP": tmp},
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            releases = repo / "build/historical"
            self.assertEqual([p.name for p in releases.iterdir()], [good])
            artifacts.verify(releases / good, good)
            self.assertEqual((releases / good / artifacts.EXTENSION).read_text().strip(), good)
