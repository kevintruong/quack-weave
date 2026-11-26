import pathlib
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

from prepare_ladybug_deps import verify


ROOT = pathlib.Path(__file__).resolve().parents[1] / "build" / "deps" / "gql-antlr"
GITHUB = "https://codeload.github.com"
DUCKGQL_REVISION = "b4421c5cb5e3a389f9658de591a0aa6d397da991"
ANTLR_VERSION = "4.13.2"
DUCKDB_REVISION = "8d78114e90a53823803660bf821f6073ac87da8c"


def install(name, url, digest, subtree, marker, *, flat=False):
    archive = ROOT / name
    installed = ROOT / subtree
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        staging = pathlib.Path(directory)
        if not archive.is_file():
            download = staging / name
            with urllib.request.urlopen(url, timeout=60) as source, download.open("wb") as output:
                shutil.copyfileobj(source, output)
            verify(download, digest)
            download.replace(archive)
        else:
            verify(archive, digest)

        if (installed / marker).is_file():
            return

        unpacked = staging / subtree
        if flat:
            unpacked.mkdir()
        with tarfile.open(archive) as contents:
            contents.extractall(unpacked if flat else staging, filter="data")
        if not (unpacked / marker).is_file():
            raise ValueError(f"Unexpected archive layout for {name}")
        try:
            unpacked.replace(installed)
        except OSError:
            if not (installed / marker).is_file():
                raise


def install_duckdb_headers():
    # Grammar extensions use DuckDB's exact C++ ABI. A shallow checkout verifies
    # the source identity independently of the platform of the loading process.
    destination = ROOT.parent / f"duckdb-{DUCKDB_REVISION}"
    checkout = ROOT.parents[2] / "duckdb"
    if not destination.exists() and (checkout / "src/include/duckdb.hpp").is_file():
        verify_duckdb_revision(checkout)
        try:
            destination.symlink_to(checkout, target_is_directory=True)
        except FileExistsError:
            pass
    if not destination.exists():
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as directory:
            staged = pathlib.Path(directory) / "source"
            subprocess.run(["git", "clone", "--depth", "1", "--branch", "v2.0.1",
                            "https://github.com/duckdb/duckdb.git", str(staged)], check=True)
            verify_duckdb_revision(staged)
            staged.rename(destination)
    verify_duckdb_revision(destination)


def verify_duckdb_revision(path):
    revision = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
    if revision != DUCKDB_REVISION:
        raise ValueError(f"{path} is not the pinned DuckDB grammar source {DUCKDB_REVISION}")


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    install_duckdb_headers()
    target, checksum = {
        ("Linux", "aarch64"): ("linux-arm64", "3d581ff935f1836363cc459e640737cdc1892ab3ed69e74853e93f01d9d071f0"),
        ("Linux", "x86_64"): ("linux-amd64", "2d5655fd5948dfb0cd16df5fc8f7cdf0b37948374cf0629af995cf4a5e3a4c82"),
        ("Darwin", "arm64"): ("osx-arm64", "adaada35202db67d010b06277320aa700f1313d9997b549a948349c9fd749a41"),
    }[platform.system(), platform.machine()]
    asset = f"duckdb-static-libs-{target}.tar.gz"
    install(
        asset, f"https://github.com/duckdb/duckdb/releases/download/v2.0.1/{asset}", checksum,
        f"duckdb-static-v2.0.1-{target}" if target.startswith("linux-") else "duckdb-static-v2.0.1",
        "libduckdb_static.a",
        flat=True,
    )
    install(
        "duckdb-gql.tar.gz",
        f"{GITHUB}/rahul-iyer/duckdb-gql/tar.gz/{DUCKGQL_REVISION}",
        "dee2af5a01118beec5b4b58fc31531361515a4bd78b07e63c468d9d6e30cf41e",
        f"duckdb-gql-{DUCKGQL_REVISION}",
        "src/parser/generated/GQLParser.cpp",
    )
    install(
        "antlr4.tar.gz",
        f"{GITHUB}/antlr/antlr4/tar.gz/refs/tags/{ANTLR_VERSION}",
        "9f18272a9b32b622835a3365f850dd1063d60f5045fb1e12ce475ae6e18a35bb",
        f"antlr4-{ANTLR_VERSION}",
        "runtime/Cpp/runtime/src/antlr4-runtime.h",
    )


if __name__ == "__main__":
    main()
