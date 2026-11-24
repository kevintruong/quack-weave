import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class NativePackageTest(unittest.TestCase):
    def test_native_target_builds_the_product_artifact(self):
        result = subprocess.run(
            ["make", "--dry-run", "mvp1"], cwd=ROOT, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("quack_weave.duckdb_extension", result.stdout)

    def test_footer_identifies_exact_unstable_duckdb_abi(self):
        with tempfile.TemporaryDirectory() as directory:
            raw_library = pathlib.Path(directory) / "libsample.dylib"
            extension = pathlib.Path(directory) / "quack_weave.duckdb_extension"
            raw_library.write_bytes(b"fake library")
            result = subprocess.run(
                [sys.executable, "scripts/package_mvp1.py", str(raw_library), str(extension), "v2.0.1", "osx_arm64", "v0.1.0"],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertTrue(extension.is_file(), result.stderr)
            payload = extension.read_bytes()
            self.assertTrue(payload.startswith(raw_library.read_bytes()))
            metadata = payload[-512:-256]
            words = [metadata[index : index + 32].rstrip(b"\0") for index in range(0, 256, 32)]
            self.assertEqual(words[3:], [b"C_STRUCT_UNSTABLE", b"v0.1.0", b"v2.0.1", b"osx_arm64", b"4"])
            self.assertEqual(payload[-256:], bytes(256))

    def test_template_build_has_separate_compatibility_feature(self):
        metadata = subprocess.check_output(
            ["cargo", "metadata", "--locked", "--offline", "--no-deps", "--format-version", "1"],
            cwd=ROOT,
            text=True,
        )
        native = next(package for package in json.loads(metadata)["packages"] if package["name"] == "rusty_quack")
        self.assertIn("template-compat", native["features"])

    @unittest.skipUnless(os.environ.get("QUACK_WEAVE_TEST_ARTIFACT"), "requires a native package")
    def test_native_binary_uses_only_system_runtime_dependencies(self):
        artifact = os.environ["QUACK_WEAVE_TEST_ARTIFACT"]
        linked = subprocess.check_output(["otool", "-L", artifact], cwd=ROOT, text=True)
        # The first entry after the file name is the dylib's own install name.
        imports = [line.strip().split(" (compatibility version", 1)[0] for line in linked.splitlines()[2:]]
        self.assertTrue(imports, linked)
        for dependency in imports:
            self.assertTrue(dependency.startswith(("/usr/lib/", "/System/Library/")), linked)
        exported = subprocess.check_output(["nm", "-gU", artifact], cwd=ROOT, text=True)
        self.assertEqual([line.split()[-1] for line in exported.splitlines()], ["_quack_weave_init_c_api_v2"])


if __name__ == "__main__":
    unittest.main()
