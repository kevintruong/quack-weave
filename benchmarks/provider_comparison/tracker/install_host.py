"""Install the unmodified DuckDB release-build SQLLogic executable and ADBC host."""
import argparse
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile


# duckdb/duckdb Actions run 44520268851, tag v2.0.1, commit 8d78114e90.
BUILDS = {
    ("Linux", "aarch64"): ("linux-release-arm64-compat-build.tar.gz", "14528027296",
                           "87e020c015d03a0f06746083de5dc4efc6c92cf093437493c5800081fabcaa01", "so"),
    ("Darwin", "arm64"): ("osx-release-arm64-build.tar.gz", "14527937468",
                          "5efebac37d5a19a029e6bb2b394d79c0c7ed97953764c74419bc78046e5245e3", "dylib"),
}


def install(cache, output, mirror):
    name, artifact, checksum, suffix = BUILDS[platform.system(), platform.machine()]
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / name
    with tempfile.TemporaryDirectory(dir=cache) as directory:
        candidate = archive if archive.is_file() else Path(directory) / name
        if candidate != archive:
            if mirror:
                subprocess.run(["curl", "--fail", "--location", "--retry", "3", "--output", candidate,
                                f"{mirror.rstrip('/')}/{name}"], check=True)
            else:
                # These archive:false artifacts are served as raw gzip by the GitHub API.
                with candidate.open("wb") as sink:
                    subprocess.run(["gh", "api", f"repos/duckdb/duckdb/actions/artifacts/{artifact}/zip"],
                                   stdout=sink, check=True)
        with candidate.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != checksum:
                raise ValueError(f"DuckDB archive SHA-256 mismatch for {name}")
        if candidate != archive:
            candidate.replace(archive)
    files = ["release/test/unittest", f"release/src/libduckdb.{suffix}"]
    with tarfile.open(archive) as release:
        for name in files:
            member = release.getmember(name)
            if not member.isfile():
                raise ValueError(f"Expected regular file {name}")
            dest = output / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            with release.extractfile(member) as source, dest.open("wb") as sink:
                shutil.copyfileobj(source, sink)
            dest.chmod(0o755)
    # Upstream embeds the absolute build directory in the SQLLogic executable's rpath.
    variable = "DYLD_LIBRARY_PATH" if suffix == "dylib" else "LD_LIBRARY_PATH"
    launcher = output / "unittest"
    launcher.write_text('#!/bin/sh\nset -eu\nhost=$(cd "$(dirname "$0")" && pwd)\n'
                        f'export {variable}="$host/release/src"\n'
                        'exec "$host/release/test/unittest" "$@"\n')
    launcher.chmod(0o755)
    (output / "upstream.sha256").write_text(checksum + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("build/duckdb-upstream"))
    parser.add_argument("--output", type=Path, default=Path("build/benchmark-host"))
    args = parser.parse_args()
    install(args.cache, args.output, os.environ.get("QW_DUCKDB_BUILD_MIRROR"))
