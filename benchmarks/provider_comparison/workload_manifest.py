"""Versioned identities shared by the Hybrid Query SQLLogic and benchmark runners."""

from hashlib import sha256
import json
from pathlib import Path
import re

import application_workloads as application
import micro_workloads as micro


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).with_name("hybrid_workloads.json")
SCHEMA_VERSION = 1
CREATOR_ALIAS = "social"
CREATOR_GRAPH = (
    f"GRAPH_TABLE ({CREATOR_ALIAS} MATCH (m:Message)-[r:Message_hasCreator_Person]->(p:Person) "
    " COLUMNS (p.PersonId AS author, m.MessageId AS mid)) AS g"
)
HEX_SHA256 = re.compile(r"[0-9a-f]{64}")
CASE_MARKER = re.compile(r"^# case: ([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)\b", re.MULTILINE)


def _source_path(relative, directory, suffix):
    if not isinstance(relative, str) or any(control in relative for control in "\0\r\n"):
        raise ValueError("Invalid hybrid workload source path")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or path.suffix != suffix:
        raise ValueError(f"Invalid hybrid workload source path: {relative!r}")
    try:
        resolved = (ROOT / path).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ValueError(f"Cannot resolve hybrid workload source path: {relative!r}") from error
    if not resolved.is_relative_to(ROOT / directory) or resolved.suffix != suffix or not resolved.is_file():
        raise ValueError(f"Hybrid workload source path is outside {directory} or is not a {suffix} file: {relative!r}")
    return resolved


def _tiny_fixture_path(tiny):
    return _source_path(tiny["path"], "test/stabilization/fixtures", ".json")


def sqllogic_path(ref):
    ids = ref["case_ids"]
    if not isinstance(ids, list):
        raise ValueError("Hybrid workload SQLLogic case markers must be a list")
    directory = "test/stabilization/sqllogic" if ids else "benchmarks/provider_comparison/tracker"
    path = _source_path(ref["path"], directory, ".test")
    if ids and CASE_MARKER.findall(path.read_text(encoding="utf-8")) != ids:
        raise ValueError(f"Hybrid workload SQLLogic case markers differ for {ref['path']!r}")
    return path


def canonical_sha256(value):
    # Order mapping keys while preserving the order and multiplicity of parameter vectors.
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return sha256(data.encode("utf-8")).hexdigest()


def micro_statements():
    return micro.statements(CREATOR_GRAPH)


def load_manifest():
    document = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if document["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported hybrid workload manifest schema")

    templates = {**micro_statements(), **application.statements()}
    cases = {}
    for case in document["cases"]:
        case_id = case["case_id"]
        if case_id in cases or case_id not in templates:
            raise ValueError(f"Duplicate or unknown hybrid workload case {case_id!r}")
        if type(case["case_revision"]) is not int or case["case_revision"] < 1:
            raise ValueError(f"Invalid revision for hybrid workload case {case_id!r}")
        template_digest = sha256(templates[case_id].encode("utf-8")).hexdigest()
        if case["sql_template_sha256"] != template_digest:
            raise ValueError(f"SQL template changed for {case_id!r}; update its manifest revision and digest")
        for ref in case["sql_logic_refs"]:
            sqllogic_path(ref)
        if "tiny_fixture" in case:
            _tiny_fixture_path(case["tiny_fixture"])
        cases[case_id] = case

    if missing := templates.keys() - cases.keys():
        raise ValueError(f"Missing hybrid workload cases: {', '.join(sorted(missing))}")
    return cases


def read_tiny_fixture(case):
    tiny = case["tiny_fixture"]
    fixture = json.loads(_tiny_fixture_path(tiny).read_text(encoding="utf-8"))
    if (not isinstance(fixture, dict) or type(fixture.get("schema_version")) is not int
            or fixture["schema_version"] != tiny["schema_version"]
            or canonical_sha256(fixture) != tiny["logical_sha256"]):
        raise ValueError(f"Hybrid workload {case['case_id']} tiny fixture differs from its manifest")

    def bigint(value):
        return type(value) is int and -(1 << 63) <= value < (1 << 63)

    edges = fixture.get("edges")
    if not isinstance(edges, list) or not edges or any(
        not isinstance(row, list) or len(row) != 2 or not all(map(bigint, row)) for row in edges
    ):
        raise ValueError("Hybrid workload tiny fixture edges must be pairs of BIGINT values")
    people = fixture.get("people")
    if not isinstance(people, list) or not people or any(
        not isinstance(row, list) or len(row) != 3 or (row[0] is not None and not bigint(row[0]))
        or not bigint(row[1]) or not bigint(row[2]) for row in people
    ):
        raise ValueError("Hybrid workload tiny fixture people must have a nullable BIGINT key and two BIGINT values")
    return fixture


def workload_evidence(case, *, scale, fixture_sha256, sql, parameters, oracle_rows, oracle_sha256):
    if not isinstance(scale, str) or not scale.strip():
        raise ValueError("Hybrid workload scale must be nonempty")
    if not HEX_SHA256.fullmatch(fixture_sha256) or not HEX_SHA256.fullmatch(oracle_sha256):
        raise ValueError("Hybrid workload fixture and oracle must have valid SHA-256 digests")
    if type(oracle_rows) is not int or oracle_rows < 0:
        raise ValueError("Hybrid workload oracle row count must be a nonnegative integer")

    identity = {
        "case_id": case["case_id"],
        "case_revision": case["case_revision"],
        "scale": scale,
        "fixture_sha256": fixture_sha256,
        "sql_template_sha256": case["sql_template_sha256"],
        "sql_sha256": sha256(sql.encode("utf-8")).hexdigest(),
        "parameter_trace_sha256": canonical_sha256(parameters),
        "oracle_key": case["case_id"],
        "oracle": case["oracle"],
        "oracle_rows": oracle_rows,
        "oracle_sha256": oracle_sha256,
        "result_schema": case["result_schema"],
        "comparison": case["comparison"],
    }
    return {
        **identity,
        "sql_logic_refs": case["sql_logic_refs"],
        "workload_sha256": canonical_sha256(identity),
    }
