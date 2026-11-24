import argparse
from pathlib import Path
import shutil
import tempfile

from package_mvp1 import package
from prepare_gql_deps import ANTLR_VERSION, DUCKDB_REVISION, DUCKGQL_REVISION, ROOT
from prepare_mvp1_deps import verify


def package_mvp2(library, extension, duckdb_version, platform, extension_version, relate=False):
    duckgql = ROOT / f"duckdb-gql-{DUCKGQL_REVISION}"
    licenses = (
        ("DuckDB-LICENSE", ROOT.parent / f"duckdb-{DUCKDB_REVISION}" / "LICENSE",
         "075c33400ffcb0c586dd106a029d3e733e9da3693f8fcb9cebfc651c8a2f14e3"),
        ("DuckGQL-LICENSE", duckgql / "LICENSE",
         "bc65d3cde8d481d55c682ee88518ded59793453091a9f34edd3f1957d0251e8a"),
        ("openGQL-LICENSE", duckgql / "third_party" / "opengql" / "LICENSE",
         "43070e2d4e532684de521b885f385d0841030efa2b1a20bafb76133a5e1379c1"),
        ("ANTLR-LICENSE.txt", ROOT / f"antlr4-{ANTLR_VERSION}" / "LICENSE.txt",
         "3db1fb3ee79a4b4f9918fc4d0f6133bf18a3cf787f126cd22f8aa9b862281c0c"),
    )
    if relate:
        source = Path(__file__).resolve().parents[1] / "crates/native/licenses/relate-1.2.0"
        licenses += (
            ("Relate-LICENSE", source / "LICENSE",
             "ac87d12e27d69f09130a7b4178e48e995ab131e4b476aa188e58ffac7ed7fab3"),
            ("Relate-THIRDPARTY-NOTICES.md", source / "THIRDPARTY-NOTICES.md",
             "d81c94a78eeb4b2bba3052cb3740bdd2f234b377f8063ad4ae59816af1718172"),
        )
    extension.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=extension.parent) as directory:
        staged = Path(directory)
        for name, source, digest in licenses:
            notice = staged / name
            shutil.copyfile(source, notice)
            verify(notice, digest)

        staged_extension = staged / extension.name
        package(library, staged_extension, duckdb_version, platform, extension_version)
        destination = extension.parent / "licenses"
        destination.mkdir(exist_ok=True)
        for name, _, _ in licenses:
            (staged / name).replace(destination / name)
        staged_extension.replace(extension)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Package QuackWeave with its GQL third-party notices")
    parser.add_argument("library", type=Path)
    parser.add_argument("extension", type=Path)
    parser.add_argument("duckdb_version")
    parser.add_argument("platform")
    parser.add_argument("extension_version")
    parser.add_argument("--relate", action="store_true", help="Include third-party notices for the RelateDB build")
    package_mvp2(**vars(parser.parse_args()))
