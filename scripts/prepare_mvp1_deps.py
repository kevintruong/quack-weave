import hashlib
import pathlib
import platform
import shutil
import tarfile
import tempfile
import urllib.request


VERSION = "0.22.3"
ROOT = pathlib.Path(__file__).resolve().parents[1] / "build" / "deps" / f"ladybug-{VERSION}"
RELEASE = f"https://github.com/LadybugDB/ladybug/releases/download/v{VERSION}"
SOURCE = f"https://codeload.github.com/LadybugDB/ladybug/tar.gz/refs/tags/v{VERSION}"


def verify(archive, digest):
    with archive.open("rb") as contents:
        if hashlib.file_digest(contents, "sha256").hexdigest() != digest:
            raise ValueError(f"SHA-256 mismatch for {archive}")


def install_archive(name, url, digest, subtree, marker):
    archive = ROOT / name
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        staging = pathlib.Path(directory)
        if not archive.exists():
            download = staging / name
            with urllib.request.urlopen(url, timeout=60) as source, download.open("wb") as output:
                shutil.copyfileobj(source, output)
            verify(download, digest)
            download.replace(archive)
        else:
            verify(archive, digest)

        installed = ROOT / subtree
        if (installed / marker).is_file():
            return

        # Source has its own top-level directory. The library archive is flat.
        is_source = subtree.startswith("ladybug-")
        destination = staging if is_source else staging / subtree
        with tarfile.open(archive) as contents:
            contents.extractall(destination, filter="data")
        if not (staging / subtree / marker).is_file():
            raise ValueError(f"Unexpected archive layout for {name}")
        try:
            (staging / subtree).replace(installed)
        except OSError:
            if not (installed / marker).is_file():
                raise


def main():
    if (platform.system(), platform.machine()) != ("Darwin", "arm64"):
        raise SystemExit("The MVP1 dependency installer targets macOS arm64.")

    ROOT.mkdir(parents=True, exist_ok=True)
    install_archive(
        "liblbug-static-osx-arm64.tar.gz",
        f"{RELEASE}/liblbug-static-osx-arm64.tar.gz",
        "9a6e6903ed36ad58fbc31412cf4aae6d269b90219137a8e29b47472a89c350c8",
        "static",
        "liblbug.a",
    )
    install_archive(
        "source.tar.gz",
        SOURCE,
        "af970748d21a20d5915f76b895272f8eda5b6b86a1cfb61e5b97f01f290f5036",
        f"ladybug-{VERSION}",
        "src/include/parser/parser.h",
    )


if __name__ == "__main__":
    main()
