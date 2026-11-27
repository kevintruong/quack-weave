import fcntl
import hashlib
import os
import pathlib
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request


VERSION = "0.23.0"
EXTENSIONS_REVISION = "3e6d45bba993dbcb0a2b80921b9fa5f544b44bb6"
ROOT = pathlib.Path(__file__).resolve().parents[1] / "build" / "deps" / f"ladybug-{VERSION}"
PATCH = pathlib.Path(__file__).with_name("ladybug_cloud.patch")
SOURCE_DIR = ROOT / f"ladybug-{VERSION}"
BUILD_DIR = ROOT / "native"

SOURCES = (
    ("source.tar.gz", f"https://codeload.github.com/LadybugDB/ladybug/tar.gz/refs/tags/v{VERSION}",
     "06ce668379897537c9638da7bc27247dde79194807b07ac75e18b3dfdb12542d"),
    ("extensions.tar.gz", f"https://codeload.github.com/LadybugDB/extensions/tar.gz/{EXTENSIONS_REVISION}",
     "20aeae96c04b39d657cb2b3f33a34c934397969f90c867424e33c72c01e606bd"),
)


def verify(archive, digest):
    with archive.open("rb") as contents:
        if hashlib.file_digest(contents, "sha256").hexdigest() != digest:
            raise ValueError(f"SHA-256 mismatch for {archive}")


def archive_path(name, url, digest):
    archive = ROOT / name
    if not archive.exists():
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            staging = pathlib.Path(directory) / name
            with urllib.request.urlopen(url, timeout=60) as source, staging.open("wb") as output:
                shutil.copyfileobj(source, output)
            verify(staging, digest)
            staging.replace(archive)
    else:
        verify(archive, digest)
    return archive


def prepare_sources():
    fingerprint = hashlib.sha256(PATCH.read_bytes()).hexdigest()
    marker = SOURCE_DIR / ".quack-weave-ladybug-patch"
    if marker.is_file() and marker.read_text(encoding="ascii") == fingerprint:
        return
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        staging = pathlib.Path(directory)
        for archive in (archive_path(*entry) for entry in SOURCES):
            with tarfile.open(archive) as contents:
                contents.extractall(staging, filter="data")
        source = staging / SOURCE_DIR.name
        extension = source / "extension"
        extension.rmdir()
        (staging / f"extensions-{EXTENSIONS_REVISION}").replace(extension)
        subprocess.run(["patch", "--batch", "-p1", "-i", str(PATCH)], cwd=source, check=True)
        (source / marker.name).write_text(fingerprint, encoding="ascii")
        previous = staging / "previous"
        if SOURCE_DIR.exists():
            SOURCE_DIR.replace(previous)
        try:
            source.replace(SOURCE_DIR)
        except OSError:
            if previous.exists():
                previous.replace(SOURCE_DIR)
            raise


def main():
    system = platform.system(), platform.machine()
    if system not in {("Darwin", "arm64"), ("Linux", "aarch64")}:
        raise SystemExit(f"Unsupported native target {system}")

    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / ".prepare.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        prepare_sources()
        args = [
            "cmake", "-S", str(SOURCE_DIR), "-B", str(BUILD_DIR),
            "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_SHARED_LBUG=OFF",
            "-DBUILD_STATIC_LBUG=ON", "-DBUILD_SINGLE_FILE_HEADER=OFF",
            "-DAUTO_UPDATE_GRAMMAR=OFF", "-DEXTENSION_STATIC_LINK_LIST=httpfs",
            "-DOPENSSL_USE_STATIC_LIBS=ON",
        ]
        openssl_root = os.environ.get("OPENSSL_ROOT_DIR")
        openssl_lib = os.environ.get("OPENSSL_LIB_DIR")
        if system[0] == "Darwin" and not openssl_root:
            openssl_root = subprocess.check_output(
                ["brew", "--prefix", "openssl@3"], text=True,
            ).strip()
        if openssl_root:
            args.append(f"-DOPENSSL_ROOT_DIR={openssl_root}")
            if not openssl_lib:
                openssl_lib = pathlib.Path(openssl_root) / "lib"
        if openssl_lib:
            for library in ("ssl", "crypto"):
                archive = pathlib.Path(openssl_lib) / f"lib{library}.a"
                if not archive.is_file():
                    raise FileNotFoundError(archive)
                args.append(f"-DOPENSSL_{library.upper()}_LIBRARY={archive}")
        subprocess.run(args, check=True)
        jobs = os.environ.get("CMAKE_BUILD_PARALLEL_LEVEL") or str(os.cpu_count() or 1)
        subprocess.run(
            ["cmake", "--build", str(BUILD_DIR), "--target", "lbug_shell", "--parallel", jobs],
            check=True,
        )


if __name__ == "__main__":
    main()
