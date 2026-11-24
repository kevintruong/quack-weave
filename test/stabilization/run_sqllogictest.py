#!/usr/bin/env python3
"""Provision Ladybug fixtures and execute the suite with DuckDB's native test runner."""

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from mvp1_acceptance import LADYBUG_VERSION, ladybug


SNAPSHOT = """\
MATCH (d:Document) RETURN d.id AS id, d.title AS title, d.active AS active, d.ratio AS ratio ORDER BY id;
MATCH (a:Document)-[:LINKS_TO]->(b:Document) RETURN a.id AS src, b.id AS dst ORDER BY src, dst;
MATCH (v:VectorRow) RETURN v.id AS vector_id ORDER BY vector_id;
MATCH (d:Document)-[:HAS_SAMPLE]->(v:VectorRow) RETURN d.id AS src, v.id AS sample ORDER BY src, sample;
CALL show_tables() RETURN name AS table_name ORDER BY table_name;
"""

NOTICE_HASHES = {
    "DuckGQL-LICENSE": "bc65d3cde8d481d55c682ee88518ded59793453091a9f34edd3f1957d0251e8a",
    "openGQL-LICENSE": "43070e2d4e532684de521b885f385d0841030efa2b1a20bafb76133a5e1379c1",
    "ANTLR-LICENSE.txt": "3db1fb3ee79a4b4f9918fc4d0f6133bf18a3cf787f126cd22f8aa9b862281c0c",
}


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False), encoding="utf-8")


def snapshot(binary, graph, target):
    write_json(target, ladybug(binary, graph, SNAPSHOT, read_only=True))


def write_package_observations(package, export, target):
    with package.open("rb") as handle:
        handle.seek(-512, os.SEEK_END)
        footer = handle.read(256)
    names = ("abi", "extension_version", "duckdb_version", "platform", "metadata_format")
    words = [footer[i : i + 32].rstrip(b"\0").decode("ascii") for i in range(0, 256, 32)]
    records = [("footer", name, value, "") for name, value in zip(names, words[3:])]
    linked = subprocess.check_output(["otool", "-L", package], text=True).splitlines()[2:]
    for line in linked:
        records.append(("import", "", line.strip().split(" (compatibility version", 1)[0], ""))
    exported = subprocess.check_output(["nm", "-gU", package], text=True).splitlines()
    records.extend(("export", "", line.split()[-1], "") for line in exported if line.strip())
    records.append(("filesystem", "export_exists", str(int(export.exists())), ""))
    for name, expected in NOTICE_HASHES.items():
        notice = package.parent / "licenses" / name
        actual = hashlib.sha256(notice.read_bytes()).hexdigest() if notice.is_file() else "missing"
        records.append(("notice", name, actual, expected))
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("kind", "name", "observed", "expected"))
        writer.writerows(records)


def run_cases(unittest, scratch, variables, files=(), stdin=None):
    env = {key: value for key, value in os.environ.items() if not key.startswith(("DYLD_", "LD_"))}
    env.update({key: str(value) for key, value in variables.items()})
    args = [unittest, "--test-dir", scratch, "--emit-test-events"]
    if variables:
        args += ["--env-passthrough", ",".join(variables)]
    if stdin is None:
        manifest = scratch / "slt-files.txt"
        manifest.write_text("\n".join(str(file) for file in files) + "\n", encoding="utf-8")
        args += ["-f", manifest]
        expected = {
            str(file): len(re.findall(r"^(?:query [TIR]+|statement (?:ok|error))\b", file.read_text(), re.M))
            for file in files
        }
    else:
        args.append("--stdin")
        expected = {"<stdin>": 1}
    result = subprocess.run(
        args, input=stdin, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env=env, cwd=scratch, timeout=120, check=False,
    )
    print(result.stdout, end="")
    completed = {}
    for line in result.stdout.splitlines():
        if "[TEST_EVENT] " in line:
            event = json.loads(line.split("[TEST_EVENT] ", 1)[1])
            if event.get("event") == "end":
                name = event["name"]
                if name in completed:
                    raise SystemExit(f"Duplicate SQLLogicTest terminal event for {name}")
                completed[name] = event.get("passes", 0) if event.get("status") == "ok" else None
    if result.returncode or completed != expected:
        raise SystemExit(f"SQLLogicTest expected {expected}, observed {completed}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duckdb-unittest", required=True, type=Path)
    parser.add_argument("--lbug", required=True, type=Path)
    parser.add_argument("--extension", required=True, type=Path)
    parser.add_argument("--without-gql", action="store_true")
    args = parser.parse_args()
    unittest = args.duckdb_unittest.resolve(strict=True)
    lbug = args.lbug.resolve(strict=True)
    package = args.extension.resolve(strict=True)
    if subprocess.check_output([lbug, "-v"], text=True).split()[-1] != LADYBUG_VERSION:
        parser.error(f"Ladybug {LADYBUG_VERSION} is required")

    with tempfile.TemporaryDirectory(prefix="qw-stabilization-") as directory:
        scratch = Path(directory).resolve()
        run_cases(unittest, scratch, {}, stdin="query T\nSELECT version();\n----\nv2.0.1\n\n")
        graph = scratch / "graph.lbdb"
        ladybug(lbug, graph, (HERE / "fixtures/read_graph.cypher").read_text(encoding="utf-8"))
        corrupt = scratch / "corrupt.lbdb"
        corrupt.write_bytes(b"not a Ladybug graph")
        export = scratch / "unexpected-export.csv"
        relocated = scratch / "relocated artifact" / "quack_weave.duckdb_extension"
        relocated.parent.mkdir()
        shutil.copy2(package, relocated)
        variables = {
            "QW_GRAPH": graph, "QW_CORRUPT": corrupt, "QW_EXPORT": export,
            "QW_EXT": relocated, "QW_ROOT": scratch,
        }
        test_dir = HERE / "sqllogic"
        if args.without_gql:
            run_cases(unittest, scratch, variables, [test_dir / "feature_off.test"])
            return

        before = scratch / "before.json"
        after = scratch / "after.json"
        observations = scratch / "package.csv"
        snapshot(lbug, graph, before)
        run_cases(unittest, scratch, variables, [test_dir / name for name in (
            "reads.test", "bind.test", "admission.test", "scan.test", "host_access.test", "limits.test",
            "timeout.test_slow", "artifact.test",
        )])
        snapshot(lbug, graph, after)
        write_package_observations(package, export, observations)
        run_cases(unittest, scratch, {"QW_BEFORE": before, "QW_AFTER": after, "QW_PACKAGE": observations},
                  [test_dir / "fixture_audit.test"])


if __name__ == "__main__":
    main()
