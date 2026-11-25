"""Stage or verify the dual-provider DuckDB release passed between CI jobs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from ci import checked_sha


PROFILE = "mvp2-relate-release/osx_arm64/duckdb-v2.0.1"
PACKAGE = Path("build/mvp2-relate/release/extension/quack_weave")
EXTENSION = "quack_weave.duckdb_extension"


def digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def stage(checkout, output):
    sha = checked_sha(subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip())
    source = checkout / PACKAGE
    if not (source / "licenses/Relate-LICENSE").is_file():
        raise ValueError("Expected the packaged release with RelateDB")
    folder = output / sha
    shutil.copytree(source, folder)
    manifest = {"commit": sha, "profile": PROFILE, "sha256": digest(folder / EXTENSION)}
    (folder / "manifest.json").write_text(json.dumps(manifest) + "\n")


def verify(folder, sha):
    manifest = json.loads((folder / "manifest.json").read_text())
    if manifest != {"commit": checked_sha(sha), "profile": PROFILE, "sha256": digest(folder / EXTENSION)}:
        raise ValueError(f"Release artifact identity or SHA-256 mismatch for {sha}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    produce = sub.add_parser("stage")
    produce.add_argument("checkout", type=Path)
    produce.add_argument("output", type=Path)
    consume = sub.add_parser("verify")
    consume.add_argument("folder", type=Path)
    consume.add_argument("commit")
    args = parser.parse_args()
    if args.cmd == "stage":
        stage(args.checkout, args.output)
    else:
        verify(args.folder, args.commit)
