import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

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

    def test_community_release_builds_the_product_for_requested_platform(self):
        targets = (
            ("Linux", "x86_64", "linux_amd64", "x86_64-unknown-linux-gnu"),
            ("Linux", "aarch64", "linux_arm64", "aarch64-unknown-linux-gnu"),
            ("Darwin", "arm64", "osx_arm64", "aarch64-apple-darwin"),
        )
        for system, machine, platform, target in targets:
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as directory:
                uname = pathlib.Path(directory) / "uname"
                uname.write_text(f'#!/bin/sh\ncase "$1" in -s) echo {system};; -m) echo {machine};; esac\n')
                uname.chmod(0o755)
                env = {**os.environ, "PATH": f"{directory}:{os.environ['PATH']}",
                       "EXTENSION_NAME": "quack_weave", "DUCKDB_PLATFORM": platform}
                result = subprocess.run(["make", "-n", "release"], cwd=ROOT, env=env,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"--target {target}", result.stdout)
                self.assertIn("build/release/extension/quack_weave/quack_weave.duckdb_extension", result.stdout)
                self.assertNotIn("template-compat", result.stdout)

    def test_linux_distribution_uses_a_host_built_fixture_inside_the_container(self):
        env = {**os.environ, "CI_EXTENSION_NAME": "quack_weave", "DUCKDB_PLATFORM": "linux_amd64"}
        for target, in_docker, expected in (
            ("configure_ci", "0", "--prepare-release-fixture"),
            ("test_release", "1", "--release-fixture"),
            ("test_release", "0", "--lbug"),
        ):
            with self.subTest(target=target, in_docker=in_docker):
                result = subprocess.run(
                    ["make", "--dry-run", target], cwd=ROOT,
                    env={**env, "LINUX_CI_IN_DOCKER": in_docker}, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(expected, result.stdout)
                if in_docker == "1":
                    self.assertNotIn("--lbug", result.stdout)

    def test_linux_amd64_dependency_archives(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import prepare_gql_deps
            import prepare_ladybug_deps
        finally:
            sys.path.pop(0)
        for module, call, asset in (
            (prepare_gql_deps, "install", "duckdb-static-libs-linux-amd64.tar.gz"),
            (prepare_ladybug_deps, "install_archive", "liblbug-static-linux-x86_64-compat.tar.gz"),
        ):
            with self.subTest(asset=asset), tempfile.TemporaryDirectory() as directory:
                with patch.object(module, "ROOT", pathlib.Path(directory)), \
                     patch.object(module.platform, "system", return_value="Linux"), \
                     patch.object(module.platform, "machine", return_value="x86_64"), \
                     patch.object(module, call) as install:
                    if module is prepare_gql_deps:
                        with patch.object(module, "install_duckdb_headers"):
                            module.main()
                    else:
                        module.main()
                self.assertEqual(install.call_args_list[0].args[0], asset)

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
    def test_native_package_includes_the_project_license(self):
        artifact = pathlib.Path(os.environ["QUACK_WEAVE_TEST_ARTIFACT"])
        notices = artifact.parent / "licenses"
        package_without_footer = artifact.read_bytes()[:-512]
        for license_name in ("QuackWeave-LICENSE", "Ladybug-LICENSE", "OpenSSL-LICENSE.txt"):
            with self.subTest(license=license_name):
                license_file = notices / license_name
                self.assertTrue(license_file.is_file(), f"Missing {license_name} in {artifact.parent}")
                if license_name == "QuackWeave-LICENSE":
                    self.assertEqual(license_file.read_bytes(), (ROOT / "LICENSE").read_bytes())
                self.assertIn(license_file.read_bytes(), package_without_footer)

    @unittest.skipUnless(os.environ.get("QUACK_WEAVE_TEST_ARTIFACT"), "requires a native package")
    def test_native_binary_uses_only_system_runtime_dependencies(self):
        artifact = os.environ["QUACK_WEAVE_TEST_ARTIFACT"]
        imports, symbols = native_dependencies(artifact)
        self.assertTrue(imports)
        if sys.platform == "linux":
            system = {"libc.so.6", "libstdc++.so.6", "libgcc_s.so.1", "libm.so.6",
                      "libdl.so.2", "libpthread.so.0", "librt.so.1",
                      "ld-linux-aarch64.so.1", "ld-linux-x86-64.so.2"}
            self.assertTrue(set(imports) <= system, imports)
        else:
            self.assertTrue(all(dep.startswith(("/usr/lib/", "/System/Library/")) for dep in imports), imports)
        self.assertEqual(symbols, ["quack_weave_init_c_api_v2"])


if __name__ == "__main__":
    unittest.main()
