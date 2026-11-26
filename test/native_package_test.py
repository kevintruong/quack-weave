import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def native_dependencies(package):
    if sys.platform == "linux":
        linked = subprocess.check_output(["readelf", "-d", package], text=True)
        imports = re.findall(r"\(NEEDED\).*?\[(.*?)\]", linked)
        exported = subprocess.check_output(["nm", "-D", "--defined-only", "--extern-only", package], text=True)
        symbols = [line.split()[-1] for line in exported.splitlines() if line.strip()]
    else:
        linked = subprocess.check_output(["otool", "-L", package], text=True).splitlines()[2:]
        imports = [line.strip().split(" (compatibility version", 1)[0] for line in linked]
        exported = subprocess.check_output(["nm", "-gU", package], text=True)
        symbols = [line.split()[-1].removeprefix("_") for line in exported.splitlines() if line.strip()]
    return imports, symbols


class NativePackageTest(unittest.TestCase):
    def test_native_target_builds_the_product_artifact(self):
        result = subprocess.run(
            ["make", "--dry-run"], cwd=ROOT, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("scripts/package_native.py", result.stdout)
        self.assertIn("build/native/debug/extension/quack_weave/quack_weave.duckdb_extension", result.stdout)

    def test_footer_identifies_exact_unstable_duckdb_abi(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            from package_native import package
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as directory:
            raw_library = pathlib.Path(directory) / "libsample.dylib"
            extension = pathlib.Path(directory) / "quack_weave.duckdb_extension"
            raw_library.write_bytes(b"fake library")
            package(raw_library, extension, "v2.0.1", "osx_arm64", "v0.2.0")
            payload = extension.read_bytes()
            self.assertTrue(payload.startswith(raw_library.read_bytes()))
            metadata = payload[-512:-256]
            words = [metadata[index : index + 32].rstrip(b"\0") for index in range(0, 256, 32)]
            self.assertEqual(words[3:], [b"C_STRUCT_UNSTABLE", b"v0.2.0", b"v2.0.1", b"osx_arm64", b"4"])
            self.assertEqual(payload[-256:], bytes(256))

    def test_template_build_has_separate_compatibility_feature(self):
        metadata = subprocess.check_output(
            ["cargo", "metadata", "--locked", "--offline", "--no-deps", "--format-version", "1"],
            cwd=ROOT,
            text=True,
        )
        native = next(package for package in json.loads(metadata)["packages"] if package["name"] == "rusty_quack")
        self.assertIn("template-compat", native["features"])
        self.assertNotIn("gql", native["features"])

    @unittest.skipUnless(os.environ.get("QUACK_WEAVE_TEST_ARTIFACT"), "requires a native package")
    def test_native_binary_uses_only_system_runtime_dependencies(self):
        artifact = os.environ["QUACK_WEAVE_TEST_ARTIFACT"]
        imports, symbols = native_dependencies(artifact)
        self.assertTrue(imports)
        if sys.platform == "linux":
            system = {"libc.so.6", "libstdc++.so.6", "libgcc_s.so.1", "libm.so.6", "ld-linux-aarch64.so.1"}
            self.assertTrue(set(imports) <= system, imports)
        else:
            self.assertTrue(all(dep.startswith(("/usr/lib/", "/System/Library/")) for dep in imports), imports)
        self.assertEqual(symbols, ["quack_weave_init_c_api_v2"])


if __name__ == "__main__":
    unittest.main()
