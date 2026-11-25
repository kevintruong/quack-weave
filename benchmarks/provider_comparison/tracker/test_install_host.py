import hashlib
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import install_host


class UpstreamHost(unittest.TestCase):
    def test_cached_archive_is_verified_and_runner_uses_its_matching_library(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "upstream.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                for name, payload in [
                    ("release/test/unittest", b'#!/bin/sh\ncat "$LD_LIBRARY_PATH/libduckdb.so"\n'),
                    ("release/src/libduckdb.so", b"pinned-library"),
                ]:
                    member = tarfile.TarInfo(name)
                    member.size = len(payload)
                    bundle.addfile(member, io.BytesIO(payload))
            checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
            pin = {("Linux", "aarch64"): (archive.name, "123", checksum, "so")}
            output = root / "host directory"
            with (patch.dict(install_host.BUILDS, pin), patch("platform.system", return_value="Linux"),
                  patch("platform.machine", return_value="aarch64")):
                install_host.install(root, output, None)
                self.assertEqual(subprocess.check_output([output / "unittest"]), b"pinned-library")
                self.assertEqual((output / "upstream.sha256").read_text().strip(), checksum)
                archive.write_bytes(b"wrong archive")
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    install_host.install(root, output, None)
