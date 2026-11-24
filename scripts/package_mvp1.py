import argparse
import pathlib
import shutil
import tempfile


def metadata_field(text):
    value = text.encode("ascii")
    if len(value) > 32 or b"\0" in value:
        raise ValueError(f"Invalid DuckDB extension metadata field {text!r}")
    return value.ljust(32, b"\0")


def package(library, extension, duckdb_version, platform, extension_version):
    # DuckDB reads the eight 32-byte fields and the 256-byte signature from EOF.
    fields = ("", "", "", "C_STRUCT_UNSTABLE", extension_version, duckdb_version, platform, "4")
    footer = b"".join(map(metadata_field, fields)) + bytes(256)
    extension.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=extension.parent) as directory:
        staged = pathlib.Path(directory) / extension.name
        with library.open("rb") as original, staged.open("wb") as destination:
            shutil.copyfileobj(original, destination)
            destination.write(footer)
        shutil.copymode(library, staged)
        staged.replace(extension)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Package the native QuackWeave DuckDB extension")
    parser.add_argument("library", type=pathlib.Path)
    parser.add_argument("extension", type=pathlib.Path)
    parser.add_argument("duckdb_version")
    parser.add_argument("platform")
    parser.add_argument("extension_version")
    package(**vars(parser.parse_args()))
