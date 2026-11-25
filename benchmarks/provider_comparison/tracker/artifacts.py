"""Stage or verify the dual-provider DuckDB release passed between CI jobs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

from ci import checked_sha


PLATFORM = "linux_arm64" if sys.platform == "linux" else "osx_arm64"
PROFILE = f"mvp2-relate-release/{PLATFORM}/duckdb-v2.0.1"
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


def verify(folder, sha, expected_digest=None):
    manifest = json.loads((folder / "manifest.json").read_text())
    checksum = digest(folder / EXTENSION)
    if (manifest != {"commit": checked_sha(sha), "profile": PROFILE, "sha256": checksum}
            or (expected_digest is not None and checksum != expected_digest)):
        raise ValueError(f"Release artifact identity or SHA-256 mismatch for {sha}")


def github_artifact(endpoint, output):
    result = subprocess.run(["gh", "api", endpoint], stdout=output, stderr=subprocess.PIPE)
    if result.returncode:
        status = re.search(rb"\(HTTP ([0-9]{3})\)", result.stderr)
        if status and status[1] in {b"404", b"410"}:
            return False
        reason = f"HTTP {status[1].decode()}" if status else f"gh exit {result.returncode}"
        raise RuntimeError(f"Could not retrieve {endpoint} ({reason})")
    output.seek(0)
    return True


def restore_previous(snapshot, directory):
    """Restore the exact extension identified by a historical benchmark snapshot."""
    artifact = snapshot.get("actions_artifacts", {}).get("release")
    if artifact is None or artifact == "":
        return None
    if not re.fullmatch(r"[1-9][0-9]*", str(artifact)):
        raise ValueError("Invalid historical release artifact ID")
    sha = checked_sha(snapshot["workspace_head"])
    checksum = snapshot["binaries"]["extension"]
    if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError("Invalid historical extension SHA-256")
    endpoint = f"repos/{os.environ['GITHUB_REPOSITORY']}/actions/artifacts/{artifact}"
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=directory) as metadata:
        if not github_artifact(endpoint, metadata):
            return None
        info = json.load(metadata)
        if info["id"] != int(artifact) or not isinstance(info["expired"], bool):
            raise ValueError("Unexpected GitHub artifact metadata")
        if info["expired"]:
            return None

    with tempfile.TemporaryFile(dir=directory) as archive, tempfile.TemporaryDirectory(dir=directory) as tmp:
        if not github_artifact(endpoint + "/zip", archive):
            return None
        staged = Path(tmp)
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            manifests = [name for name in names if name in {f"{sha}/manifest.json", f"releases/{sha}/manifest.json"}]
            if len(manifests) != 1:
                raise ValueError(f"Expected one release manifest for {sha}")
            prefix = manifests[0].removesuffix("manifest.json")
            if names.count(prefix + EXTENSION) != 1:
                raise ValueError(f"Expected one release binary for {sha}")
            for member in ("manifest.json", EXTENSION):
                with bundle.open(prefix + member) as source, (staged / member).open("wb") as target:
                    shutil.copyfileobj(source, target)
        verify(staged, sha, checksum)
        destination = directory / sha / checksum / EXTENSION
        destination.parent.mkdir(parents=True, exist_ok=True)
        (staged / EXTENSION).replace(destination)
        return destination


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
