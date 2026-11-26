import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from prepare_gql_deps import ANTLR_VERSION, DUCKDB_REVISION, DUCKGQL_REVISION, ROOT
from prepare_ladybug_deps import ROOT as LADYBUG_ROOT, VERSION as LADYBUG_VERSION, verify


def metadata_field(text):
    value = text.encode("ascii")
    if len(value) > 32 or b"\0" in value:
        raise ValueError(f"Invalid DuckDB extension metadata field {text!r}")
    return value.ljust(32, b"\0")


def package(library, extension, duckdb_version, platform, extension_version, *, notices=()):
    # DuckDB reads the eight 32-byte fields and the 256-byte signature from EOF.
    fields = ("", "", "", "C_STRUCT_UNSTABLE", extension_version, duckdb_version, platform, "4")
    footer = b"".join(map(metadata_field, fields)) + bytes(256)
    extension.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=extension.parent) as directory:
        staged = Path(directory) / extension.name
        with library.open("rb") as original, staged.open("wb") as destination:
            shutil.copyfileobj(original, destination)
            for name, notice in notices:
                destination.write(f"\n--- Quack Weave license notice: {name} ---\n".encode("utf-8"))
                with notice.open("rb") as text:
                    shutil.copyfileobj(text, destination)
            destination.write(footer)
        shutil.copymode(library, staged)
        staged.replace(extension)


def openssl_license(platform):
    if prefix := os.environ.get("OPENSSL_LIB_DIR"):
        directory = Path(prefix)
        candidates = (directory / "LICENSE.txt", directory.parent / "LICENSE.txt")
    elif platform.startswith("osx_"):
        prefix = subprocess.check_output(["brew", "--prefix", "openssl@3"], text=True).strip()
        candidates = (Path(prefix) / "LICENSE.txt",)
    else:
        candidates = ()
    if platform.startswith("linux_") and (not prefix or directory.is_relative_to("/usr/lib")):
        candidates += (Path("/usr/share/doc/libssl-dev/copyright"),)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("Place the matching OpenSSL license in OPENSSL_LIB_DIR as LICENSE.txt")


def vendor_notices(root, component):
    filenames = ("license", "notice", "copying", "copyright")
    third_party = root / "third_party"
    for source in sorted(third_party.rglob("*")):
        if source.is_file() and any(word in source.name.lower() for word in filenames):
            yield (f"{component}/{source.relative_to(third_party)}", source, None)


def package_native(library, extension, duckdb_version, platform, extension_version):
    project = Path(__file__).resolve().parents[1]
    duckgql = ROOT / f"duckdb-gql-{DUCKGQL_REVISION}"
    ladybug = LADYBUG_ROOT / f"ladybug-{LADYBUG_VERSION}"
    duckdb = ROOT.parent / f"duckdb-{DUCKDB_REVISION}"
    relate = project / "crates/native/licenses/relate-1.2.0"
    licenses = (
        ("QuackWeave-LICENSE", project / "LICENSE",
         "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"),
        ("DuckDB-LICENSE", duckdb / "LICENSE",
         "075c33400ffcb0c586dd106a029d3e733e9da3693f8fcb9cebfc651c8a2f14e3"),
        ("Ladybug-LICENSE", ladybug / "LICENSE",
         "1c495c9546d0de02e83c9d50d5f7eb21f0085bc8f77a0ee333081a123a9c8d0c"),
        ("OpenSSL-LICENSE.txt", openssl_license(platform), None),
        ("DuckGQL-LICENSE", duckgql / "LICENSE",
         "bc65d3cde8d481d55c682ee88518ded59793453091a9f34edd3f1957d0251e8a"),
        ("openGQL-LICENSE", duckgql / "third_party" / "opengql" / "LICENSE",
         "43070e2d4e532684de521b885f385d0841030efa2b1a20bafb76133a5e1379c1"),
        ("ANTLR-LICENSE.txt", ROOT / f"antlr4-{ANTLR_VERSION}" / "LICENSE.txt",
         "3db1fb3ee79a4b4f9918fc4d0f6133bf18a3cf787f126cd22f8aa9b862281c0c"),
        ("Relate-LICENSE", relate / "LICENSE",
         "ac87d12e27d69f09130a7b4178e48e995ab131e4b476aa188e58ffac7ed7fab3"),
        ("Relate-THIRDPARTY-NOTICES.md", relate / "THIRDPARTY-NOTICES.md",
         "d81c94a78eeb4b2bba3052cb3740bdd2f234b377f8063ad4ae59816af1718172"),
    )
    licenses += tuple(vendor_notices(duckdb, "DuckDB"))
    licenses += tuple(vendor_notices(ladybug, "Ladybug"))
    extension.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=extension.parent) as directory:
        staged = Path(directory)
        for name, source, digest in licenses:
            notice = staged / name
            notice.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, notice)
            if digest:
                verify(notice, digest)

        staged_extension = staged / extension.name
        package(library, staged_extension, duckdb_version, platform, extension_version,
                notices=((name, staged / name) for name, _, _ in licenses))
        destination = extension.parent / "licenses"
        destination.mkdir(exist_ok=True)
        for name, _, _ in licenses:
            output = destination / name
            output.parent.mkdir(parents=True, exist_ok=True)
            (staged / name).replace(output)
        staged_extension.replace(extension)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Package QuackWeave with its license and third-party notices")
    parser.add_argument("library", type=Path)
    parser.add_argument("extension", type=Path)
    parser.add_argument("duckdb_version")
    parser.add_argument("platform")
    parser.add_argument("extension_version")
    package_native(**vars(parser.parse_args()))
