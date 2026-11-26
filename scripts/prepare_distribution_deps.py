"""Install pinned command-line clients and the Linux static TLS dependency for release CI."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from prepare_gql_deps import ROOT, install
from prepare_ladybug_deps import RELEASE as LADYBUG_RELEASE


DUCKDB_RELEASE = "https://github.com/duckdb/duckdb/releases/download/v2.0.1"
OPENSSL = "openssl-3.5.9"
CLIENTS = {
    "linux_amd64": (
        "linux-amd64", "b676268be4d39e4e41a904442c9796c9914e645cc085c7505f048f2c992b5eca",
        "linux-x86_64", "a6ca33a99eff74662f3906f61cf77d9feee5d21ee98fd06ffab4594c5d307779",
    ),
    "linux_arm64": (
        "linux-arm64", "84e37891fcc45c887e30220f51a4914995cd8174139e87f8efd311ac83c956a7",
        "linux-aarch64", "31f90d7da53245ab1a3b533df8d02939e5fdb60f517855a44c3ac8cd0969fbcd",
    ),
    "osx_arm64": (
        "osx-arm64", "7809dc1ea9215db53f76bdd539e38186c2310b6a3b5800581bf65876048556aa",
        "osx-arm64", "d0012ffc8683a7b88fe47b8068bf4ee12c5a7f5b5c08fde89a2e4a6acd091a90",
    ),
}


def build_openssl():
    destination = ROOT / "openssl-static"
    required = ("libcrypto.a", "libssl.a", "LICENSE.txt")
    if all((destination / file).is_file() for file in required):
        return
    archive = f"{OPENSSL}.tar.gz"
    source = ROOT / OPENSSL
    install(archive, f"https://github.com/openssl/openssl/releases/download/{OPENSSL}/{archive}",
            "603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a",
            OPENSSL, "Configure")
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        staging = Path(directory)
        subprocess.run(["perl", str(source / "Configure"), "no-shared", "no-tests",
                        "no-apps", "no-docs", "-fPIC"], cwd=staging, check=True)
        jobs = len(os.sched_getaffinity(0))
        # OpenSSL's public target generates the headers before compiling the libraries.
        subprocess.run(["make", f"-j{jobs}", "build_libs"], cwd=staging, check=True)
        package = staging / destination.name
        package.mkdir()
        for file in required[:2]:
            shutil.move(staging / file, package / file)
        shutil.copyfile(source / "LICENSE.txt", package / "LICENSE.txt")
        try:
            package.replace(destination)
        except OSError:
            if not all((destination / file).is_file() for file in required):
                raise


def prepare_clients(platform):
    duckdb, duckdb_hash, ladybug, ladybug_hash = CLIENTS[platform]
    duckdb_archive = f"duckdb-cli-{duckdb}.tar.gz"
    ladybug_archive = f"lbug_cli-{ladybug}.tar.gz"
    install(duckdb_archive, f"{DUCKDB_RELEASE}/{duckdb_archive}", duckdb_hash,
            f"duckdb-cli-{platform}", "duckdb", flat=True)
    install(ladybug_archive, f"{LADYBUG_RELEASE}/{ladybug_archive}", ladybug_hash,
            f"ladybug-cli-{platform}", "lbug", flat=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", choices=CLIENTS)
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    prepare_clients(args.platform)
    if args.platform.startswith("linux_"):
        build_openssl()
