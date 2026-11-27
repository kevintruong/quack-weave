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
import struct
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from cypher_acceptance import LADYBUG_VERSION, ladybug
from native_package_test import native_dependencies

DUCKDB_PIN_VERSION = "v2.0.1"
DUCKDB_PIN_SOURCE = "8d78114e90"
PIN_PROBE_SQL = (
    "query TT\nSELECT library_version, source_id FROM pragma_version();\n----\n"
    f"{DUCKDB_PIN_VERSION}\t{DUCKDB_PIN_SOURCE}\n\n"
)


SNAPSHOT = """\
MATCH (d:Document) RETURN d.id AS id, d.title AS title, d.active AS active, d.ratio AS ratio ORDER BY id;
MATCH (a:Document)-[:LINKS_TO]->(b:Document) RETURN a.id AS src, b.id AS dst ORDER BY src, dst;
MATCH (v:VectorRow) RETURN v.id AS vector_id ORDER BY vector_id;
MATCH (d:Document)-[:HAS_SAMPLE]->(v:VectorRow) RETURN d.id AS src, v.id AS sample ORDER BY src, sample;
CALL show_tables() RETURN name AS table_name ORDER BY table_name;
"""

NOTICE_HASHES = {
    "DuckDB-LICENSE": "075c33400ffcb0c586dd106a029d3e733e9da3693f8fcb9cebfc651c8a2f14e3",
    "DuckGQL-LICENSE": "bc65d3cde8d481d55c682ee88518ded59793453091a9f34edd3f1957d0251e8a",
    "openGQL-LICENSE": "43070e2d4e532684de521b885f385d0841030efa2b1a20bafb76133a5e1379c1",
    "ANTLR-LICENSE.txt": "3db1fb3ee79a4b4f9918fc4d0f6133bf18a3cf787f126cd22f8aa9b862281c0c",
    "Relate-LICENSE": "ac87d12e27d69f09130a7b4178e48e995ab131e4b476aa188e58ffac7ed7fab3",
    "Relate-THIRDPARTY-NOTICES.md": "d81c94a78eeb4b2bba3052cb3740bdd2f234b377f8063ad4ae59816af1718172",
}


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False), encoding="utf-8")


def report_artifact(path):
    with path.open("rb") as artifact:
        identity = {"name": str(path), "sha256": hashlib.file_digest(artifact, "sha256").hexdigest()}
    print("[QW_ARTIFACT] " + json.dumps(identity), flush=True)


def snapshot(binary, graph, fixtures, target):
    fixture_hashes = {}
    for name, path in fixtures.items():
        with path.open("rb") as database:
            fixture_hashes[f"{name}_fixture_sha256"] = hashlib.file_digest(database, "sha256").hexdigest()
    write_json(target, {
        "graph_rows": ladybug(binary, graph, SNAPSHOT, read_only=True),
        **fixture_hashes,
    })


def write_package_observations(package, export, target):
    with package.open("rb") as handle:
        handle.seek(-512, os.SEEK_END)
        footer = handle.read(256)
    names = ("abi", "extension_version", "duckdb_version", "platform", "metadata_format")
    words = [footer[i : i + 32].rstrip(b"\0").decode("ascii") for i in range(0, 256, 32)]
    records = [("footer", name, value, "") for name, value in zip(names, words[3:])]
    imports, symbols = native_dependencies(package)
    records.extend(("import", "", item, "") for item in imports)
    records.extend(("export", "", symbol, "") for symbol in symbols)
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
        source_bytes = {str(file): file.read_bytes() for file in files}
        expected = {name: len(re.findall(r"^(?:query [TIR]+|statement (?:ok|error|maybe))\b",
                                        source.decode("utf-8"), re.M))
                    for name, source in source_bytes.items()}
    else:
        args.append("--stdin")
        expected = {"<stdin>": 1}
        source_bytes = {"<stdin>": stdin.encode("utf-8")}
    for name, source in source_bytes.items():
        identity = {"name": name, "sha256": hashlib.sha256(source).hexdigest(), "blocks": expected[name]}
        print("[QW_SLT_SOURCE] " + json.dumps(identity), flush=True)
    result = subprocess.run(
        args, input=stdin, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env=env, cwd=scratch, timeout=120, check=False,
    )
    print(result.stdout, end="")
    if stdin is None and any(file.read_bytes() != source_bytes[str(file)] for file in files):
        raise SystemExit("SQLLogicTest sources changed during execution")
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


def run_creator_witness(unittest, scratch, lbug, extension):
    # The benchmark modules used here require only the standard library.
    benchmark_path = HERE.parents[1] / "benchmarks/provider_comparison"
    sys.path.insert(0, str(benchmark_path))
    try:
        import micro_workloads as micro
        import workload_manifest as workloads
    finally:
        sys.path.remove(str(benchmark_path))

    case_id = "micro_creator_selective"
    case = workloads.load_manifest()[case_id]
    fixture = workloads.read_tiny_fixture(case)

    edges = fixture["edges"]
    people = fixture["people"]
    graph_dir = scratch / "hybrid-creator"
    graph_dir.mkdir()
    graph = graph_dir / "creator.lbdb"
    graph_ddl = [
        "CREATE NODE TABLE Person(PersonId INT64 PRIMARY KEY);",
        "CREATE NODE TABLE Message(MessageId INT64 PRIMARY KEY);",
        "CREATE REL TABLE Message_hasCreator_Person(FROM Message TO Person);",
    ]
    graph_ddl.extend(f"CREATE (:Person {{PersonId: {author:d}}});" for author in sorted({a for a, _ in edges}))
    graph_ddl.extend(f"CREATE (:Message {{MessageId: {mid:d}}});" for mid in sorted({m for _, m in edges}))
    graph_ddl.extend(
        f"MATCH (m:Message {{MessageId: {mid:d}}}), (p:Person {{PersonId: {author:d}}}) "
        "CREATE (m)-[:Message_hasCreator_Person]->(p);"
        for author, mid in edges
    )
    ladybug(lbug, graph, "\n".join(graph_ddl) + "\n")

    def file_hashes():
        hashes = {}
        for path in graph_dir.iterdir():
            with path.open("rb") as handle:
                hashes[path.name] = hashlib.file_digest(handle, "sha256").hexdigest()
        return hashes

    def quote(value):
        return "'" + str(value).replace("'", "''") + "'"

    sql = workloads.micro_statements()[case_id]
    before = file_hashes()
    result = micro.expected_rows(edges, {"people": people, "messages": []})[case_id]
    # The scaled tracker uses the same whole-row, little-endian int64 encoding.
    oracle_sha256 = hashlib.sha256(b"".join(struct.pack("<qqq", *row) for row in sorted(result))).hexdigest()
    evidence = workloads.workload_evidence(
        case, scale="tiny", fixture_sha256=case["tiny_fixture"]["logical_sha256"],
        sql=sql, parameters={"people": people},
        oracle_rows=len(result), oracle_sha256=oracle_sha256,
    )
    register = json.dumps({"alias": workloads.CREATOR_ALIAS, "path": str(graph)})
    variables = {
        "QW_CREATOR_EXTENSION": quote(extension),
        "QW_CREATOR_REGISTER": "SET GLOBAL qw_ladybug_config = " + quote(register),
        "QW_CREATOR_THRESHOLD": micro.HOST_THRESHOLD,
        "QW_CREATOR_PEOPLE": micro.values_sql(people),
        "QW_CREATOR_EDGES": micro.values_sql(edges),
        "QW_CREATOR_SQL": sql,
    }
    witness = next(ref for ref in case["sql_logic_refs"] if ref["case_ids"])
    run_cases(unittest, scratch, variables, [workloads.sqllogic_path(witness)])
    if before != file_hashes():
        raise ValueError(f"Hybrid workload {case_id} changed its read-only graph fixture")
    print("[QW_HYBRID_WORKLOAD] " + json.dumps(evidence), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duckdb-unittest", required=True, type=Path)
    parser.add_argument("--lbug", required=True, type=Path)
    parser.add_argument("--extension", required=True, type=Path)
    args = parser.parse_args()
    unittest = args.duckdb_unittest.resolve(strict=True)
    lbug = args.lbug.resolve(strict=True)
    package = args.extension.resolve(strict=True)
    if subprocess.check_output([lbug, "-v"], text=True).split()[-1] != LADYBUG_VERSION:
        parser.error(f"Ladybug {LADYBUG_VERSION} is required")

    with tempfile.TemporaryDirectory(prefix="qw-stabilization-") as directory:
        scratch = Path(directory).resolve()
        run_cases(unittest, scratch, {}, stdin=PIN_PROBE_SQL)
        graph = scratch / "graph.lbdb"
        ladybug(lbug, graph, (HERE / "fixtures/read_graph.cypher").read_text(encoding="utf-8"))
        corrupt = scratch / "corrupt.lbdb"
        corrupt.write_bytes(b"not a Ladybug graph")
        export = scratch / "unexpected-export.csv"
        relocated = scratch / "relocated artifact" / "quack_weave.duckdb_extension"
        relocated.parent.mkdir()
        shutil.copy2(package, relocated)
        report_artifact(relocated)
        variables = {
            "QW_GRAPH": graph, "QW_CORRUPT": corrupt, "QW_EXPORT": export,
            "QW_EXT": relocated, "QW_ROOT": scratch,
        }
        test_dir = HERE / "sqllogic"
        duckgql_graph = scratch / "duckgql.lbdb"
        ladybug(lbug, duckgql_graph, (HERE / "fixtures/duckgql_reads.cypher").read_text(encoding="utf-8"))
        variables["QW_DUCKGQL_GRAPH"] = duckgql_graph

        replacement_graph = scratch / "replacement.lbdb"
        ladybug(lbug, replacement_graph, (HERE / "fixtures/usage_replacement.cypher").read_text(encoding="utf-8"))
        variables["QW_GRAPH_REPLACEMENT"] = replacement_graph

        air_routes = scratch / "air_routes.lbdb"
        ladybug(lbug, air_routes, (HERE / "fixtures/air_routes.cypher").read_text(encoding="utf-8"))
        variables["QW_AIR_ROUTES"] = air_routes
        amounts = scratch / "aggregate_values.lbdb"
        ladybug(lbug, amounts, (HERE / "fixtures/aggregate_values.cypher").read_text(encoding="utf-8"))
        variables["QW_AGGREGATE_VALUES"] = amounts
        archived_routes = scratch / "archived_routes.lbdb"
        shutil.copyfile(air_routes, archived_routes)
        os.utime(archived_routes, ns=(-1_000_000_001, -1_000_000_001))
        variables["QW_ARCHIVED_ROUTES"] = archived_routes
        fixtures = {"duckgql": duckgql_graph, "replacement": replacement_graph, "air_routes": air_routes,
                    "aggregate_values": amounts}

        before = scratch / "before.json"
        after = scratch / "after.json"
        observations = scratch / "package.csv"
        snapshot(lbug, graph, fixtures, before)
        run_cases(unittest, scratch, variables, [test_dir / name for name in (
            "reads.test", "gql_compatibility.test", "usage_relations.test", "usage_binding.test",
            "usage_boundary.test", "air_routes_fixture.test", "graph_metadata.test",
            "native_surface.test", "graph_entry.test", "graph_table.test",
            "graph_aggregate_pushdown.test", "table_watchlist.test", "hybrid_public.test",
            "graph_parameters.test", "declared_bindings.test", "graph_values.test",
            "bind.test", "admission.test", "scan.test", "host_access.test", "remote_policy.test", "limits.test",
            "timeout.test_slow", "artifact.test",
            "duckgql_admission.test", "duckgql_aggregates.test", "duckgql_basic.test",
            "duckgql_paths.test", "duckgql_reachability.test", "duckgql_scalars.test",
            "hybrid_directory_join_topk.test",
            "hybrid_prepared_watchlist_churn.test",
        )])
        run_creator_witness(unittest, scratch, lbug, relocated)
        snapshot(lbug, graph, fixtures, after)
        write_package_observations(package, export, observations)
        run_cases(unittest, scratch, {"QW_BEFORE": before, "QW_AFTER": after, "QW_PACKAGE": observations},
                  [test_dir / "fixture_audit.test"])


if __name__ == "__main__":
    main()
