#!/usr/bin/env python3
"""Exercise a real RelateDB bundle and Ladybug graph with DuckDB's SQLLogic runner."""

import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
STABILIZATION = HERE.parent / "stabilization"
sys.path.insert(0, str(STABILIZATION))
from run_sqllogictest import PIN_PROBE_SQL, ladybug, report_artifact, run_cases


def fixture_snapshot(directory):
    """Cover fixture contents, metadata, and any sidecars produced by either engine."""
    result = {}
    for path in directory.rglob("*"):
        if path.is_file():
            stat = path.stat()
            with path.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            result[path.relative_to(directory)] = (stat.st_mode, stat.st_mtime_ns, digest)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("fixture-builder", "duckdb-unittest", "extension", "lbug"):
        parser.add_argument(f"--{option}", required=True, type=lambda path: Path(path).resolve(strict=True))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="qw-relate-") as temp:
        scratch = Path(temp).resolve()
        fixtures = scratch / "fixtures"
        fixtures.mkdir()
        relate = fixtures / "routes.rl"
        lbug = fixtures / "routes.lbdb"
        subprocess.run([args.fixture_builder, relate], check=True, timeout=120)
        ladybug(args.lbug, lbug, (STABILIZATION / "fixtures/air_routes.cypher").read_text())
        if not relate.is_file():
            raise AssertionError("Relate fixture builder did not create a bundle file")

        relate.chmod(0o444)
        corrupt = fixtures / "corrupt.rl"
        corrupt.write_bytes(b"invalid Relate bundle")
        before = fixture_snapshot(fixtures)
        report_artifact(args.extension)
        run_cases(args.duckdb_unittest, scratch, {}, stdin=PIN_PROBE_SQL)
        run_cases(args.duckdb_unittest, scratch, {
            "QW_EXT": args.extension, "QW_RELATE": relate, "QW_LADYBUG": lbug,
            "QW_MISSING": fixtures / "missing.rl", "QW_CORRUPT": corrupt, "QW_DIR": fixtures,
        }, [HERE / "provider.test"])
        after = fixture_snapshot(fixtures)
        changed = sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))
        if changed:
            raise AssertionError(f"Graph fixture files changed during read-only queries: {changed}")


if __name__ == "__main__":
    main()
