import pathlib
import shutil
import tarfile
import tempfile
import urllib.request

from prepare_mvp1_deps import verify


ROOT = pathlib.Path(__file__).resolve().parents[1] / "build" / "deps" / "gql-antlr"
GITHUB = "https://codeload.github.com"
DUCKGQL_REVISION = "b4421c5cb5e3a389f9658de591a0aa6d397da991"
ANTLR_VERSION = "4.13.2"


def install(name, url, digest, subtree, marker):
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

        with tarfile.open(archive) as contents:
            contents.extractall(staging, filter="data")
        unpacked = staging / subtree
        if not (unpacked / marker).is_file():
            raise ValueError(f"Unexpected archive layout for {name}")
        try:
            unpacked.replace(installed)
        except OSError:
            if not (installed / marker).is_file():
                raise


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
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
