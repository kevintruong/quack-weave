#!/usr/bin/env python3
"""Verify the stabilization case manifest against SLT sources and runner logs."""

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
from itertools import groupby
from pathlib import Path

from run_sqllogictest import PIN_PROBE_SQL


HERE = Path(__file__).resolve().parent
SUITE = "test/stabilization/sqllogic"
SUITE_SUFFIXES = {".test", ".test_slow"}
CASE_ID = r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*"
CASE_MARKER = re.compile(rf"# case:[ \t]+({CASE_ID})(?:[ \t]+.*)?")
SQL_BLOCK = re.compile(r"(?:query [TIR]+|statement (?:ok|error))(?:[ \t]+.*)?")
CASE_COUNT = 142
PROFILE_COUNTS = {"native-debug": 135, "native-release": 135, "observer": 7}
NATIVE_PROFILES = ("native-debug", "native-release")
PREAMBLE_BLOCKS = {"limits.test": 2, "observer_audit.test": 6}
PIN_PROBE = "<stdin>"
SOURCE_RECORD = "[QW_SLT_SOURCE]"
TEST_EVENT = "[TEST_EVENT]"
ARTIFACT_RECORD = "[QW_ARTIFACT]"
PHASES = ("begin", "execution-begin", "execution-complete", "end")


@dataclass(frozen=True)
class SourceEvidence:
    blocks: int
    digest: str


def read_manifest():
    cases = {}
    files = defaultdict(dict)
    with (HERE / "case_manifest.csv").open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != ["case_id", "test_file", "profiles", "blocks"]:
            raise ValueError("unexpected case_manifest.csv columns")
        for row in reader:
            case, name, profile_field, blocks = (
                row["case_id"], row["test_file"], row["profiles"], row["blocks"]
            )
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"malformed manifest row {reader.line_num}")
            if not re.fullmatch(CASE_ID, case) or case in cases:
                raise ValueError(f"invalid or duplicate manifest case {case!r}")
            if not re.fullmatch(r"[a-z0-9_]+\.test(?:_slow)?", name):
                raise ValueError(f"invalid manifest test file {name!r}")
            profiles = tuple(profile_field.split("|"))
            expected_profiles = ("observer",) if name == "observer_audit.test" else NATIVE_PROFILES
            observer_case = case.startswith("observer.")
            if profiles != expected_profiles or observer_case != (profiles == ("observer",)):
                raise ValueError(f"invalid manifest profile assignment for {case!r}")
            if not re.fullmatch(r"[1-9][0-9]*", blocks):
                raise ValueError(f"manifest case {case!r} requires positive SQL block count")
            files[name][case] = int(blocks)
            cases[case] = profiles

    profile_counts = Counter(profile for profiles in cases.values() for profile in profiles)
    if len(cases) != CASE_COUNT or profile_counts != PROFILE_COUNTS:
        raise ValueError(f"manifest requires {CASE_COUNT} cases and profile counts {PROFILE_COUNTS}")
    return cases, files


def count_source_blocks(name, source):
    counts = {None: 0}
    case = None
    # A top-level SLT record ends at a blank line. Its SQL or expected output can
    # contain text that looks like a separate header, so count only record headers.
    lines = source.decode("utf-8").splitlines()
    for nonblank, record in groupby(lines, lambda line: bool(line.strip())):
        if not nonblank:
            continue
        for line in record:
            if line.startswith("# case:"):
                marker = CASE_MARKER.fullmatch(line)
                if marker is None or marker[1] in counts:
                    raise ValueError(f"{name}: invalid or repeated case marker {line!r}")
                case = marker[1]
                counts[case] = 0
            elif not line.startswith("#"):
                if SQL_BLOCK.fullmatch(line):
                    parts = (part.strip() for part in record)
                    body = next((part for part in parts if part == "----" or not part.startswith(("#", "--"))), "")
                    if not body or body == "----" or SQL_BLOCK.fullmatch(body):
                        raise ValueError(f"{name}: SQL block has no body in case {case!r}")
                    counts[case] += 1
                break
    return counts


def validate_sources(manifest_files):
    suite_dir = HERE / "sqllogic"
    suite_files = {
        path.relative_to(suite_dir).as_posix(): path
        for path in suite_dir.rglob("*")
        if path.is_file() and path.suffix in SUITE_SUFFIXES
    }
    if set(suite_files) != set(manifest_files):
        missing = sorted(set(manifest_files) - set(suite_files))
        extra = sorted(set(suite_files) - set(manifest_files))
        raise ValueError(f"SQL file inventory differs from manifest (missing={missing}, extra={extra})")

    sources = {}
    for name, path in sorted(suite_files.items()):
        expected = {None: PREAMBLE_BLOCKS.get(name, 0), **manifest_files[name]}
        source = path.read_bytes()
        actual = count_source_blocks(name, source)
        if actual != expected:
            differences = [
                f"{case or 'preamble'}={actual.get(case, 'missing')} (expected {expected.get(case, 'absent')})"
                for case in dict.fromkeys((*expected, *actual))
                if actual.get(case) != expected.get(case)
            ]
            raise ValueError(f"{name}: SQL case/block mismatch: {', '.join(differences)}")
        sources[name] = SourceEvidence(sum(actual.values()), sha256(source).hexdigest())
    return sources


def parse_record(payload, marker, location):
    try:
        record = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ValueError(f"{location}: invalid {marker} JSON") from error
    if not isinstance(record, dict):
        raise ValueError(f"{location}: {marker} must be a JSON object")
    return record


def test_name(record, expected, location):
    raw_name = record.get("name")
    if not isinstance(raw_name, str):
        raise ValueError(f"{location}: runner record has no test name")
    normalized = raw_name.replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1]
    test_path = f"{SUITE}/{name}"
    if name == PIN_PROBE:
        known_path = normalized == PIN_PROBE
    else:
        known_path = normalized in (name, test_path) or normalized.endswith(f"/{test_path}")
    if name not in expected or not known_path:
        raise ValueError(f"{location}: unexpected runner test {raw_name!r}")
    return name


def validate_log(path, expected):
    source_records = set()
    phases = dict.fromkeys(expected, 0)
    observed = {}
    artifact = None
    with path.open(encoding="utf-8") as log:
        for number, line in enumerate(log, 1):
            prefix = next(
                (tag for tag in (SOURCE_RECORD, ARTIFACT_RECORD) if line.startswith(tag)), TEST_EVENT
            )
            _, marker, payload = line.partition(prefix)
            if not marker:
                continue
            location = f"{path.name}:{number}"
            record = parse_record(payload, marker, location)
            if marker == ARTIFACT_RECORD:
                if artifact is not None:
                    raise ValueError(f"{location}: duplicate artifact identity")
                name, digest = record.get("name"), record.get("sha256")
                if not isinstance(name, str) or not name.strip() or not isinstance(digest, str) or not re.fullmatch(
                    r"[0-9a-f]{64}", digest
                ):
                    raise ValueError(f"{location}: invalid artifact identity")
                artifact = {"name": name, "sha256": digest}
                continue
            name = test_name(record, expected, location)
            source = expected[name]
            if marker == SOURCE_RECORD:
                if name in source_records:
                    raise ValueError(f"{location}: duplicate source record for {name}")
                if record.get("sha256") != source.digest:
                    raise ValueError(f"{location}: {name} source SHA-256 differs from current SQL")
                if type(record.get("blocks")) is not int or record["blocks"] != source.blocks:
                    raise ValueError(f"{location}: {name} source blocks={record.get('blocks')!r}, expected {source.blocks}")
                source_records.add(name)
                continue

            phase = record.get("event")
            index = phases[name]
            if index == len(PHASES):
                raise ValueError(f"{location}: extra {phase!r} event after {name} end")
            required_phase = PHASES[index]
            if phase != required_phase:
                raise ValueError(f"{location}: {name} has {phase!r} event, expected {required_phase!r}")
            if name not in source_records:
                raise ValueError(f"{location}: missing source record before {name} begin")
            phases[name] += 1
            if phase in ("execution-complete", "end"):
                for field, required in (("passes", source.blocks), ("fails", 0), ("skip-mode", 0)):
                    value = record.get(field)
                    if type(value) is not int or value != required:
                        raise ValueError(f"{location}: {name} {phase} has {field}={value!r}, expected {required}")
                if record.get("status") != "ok":
                    raise ValueError(f"{location}: {name} {phase} has status {record.get('status')!r}, expected 'ok'")
            if phase == "end":
                observed[name] = record["passes"]

    missing = [f"{name} {PHASES[index]}" for name, index in sorted(phases.items()) if index < len(PHASES)]
    if missing:
        raise ValueError(f"{path.name}: missing runner phases for {', '.join(missing)}")
    if artifact is None:
        raise ValueError(f"{path.name}: missing artifact identity")
    return observed, artifact


def check_coverage(report_dir):
    cases, manifest_files = read_manifest()
    sources = validate_sources(manifest_files)
    probe = SourceEvidence(1, sha256(PIN_PROBE_SQL.encode("utf-8")).hexdigest())
    profiles = {}
    for profile in PROFILE_COUNTS:
        profile_cases = {
            name: [case for case in file_cases if profile in cases[case]]
            for name, file_cases in manifest_files.items()
        }
        expected = {name: sources[name] for name, members in profile_cases.items() if members}
        observed, artifact = validate_log(report_dir / f"{profile}.log", {PIN_PROBE: probe, **expected})
        profiles[profile] = {
            "case_ids": sorted(case for members in profile_cases.values() for case in members),
            "file_blocks": {f"{SUITE}/{name}": observed[name] for name in expected},
            "pin_probe_blocks": observed[PIN_PROBE],
            "artifact": artifact,
        }
    if profiles["observer"]["artifact"]["sha256"] != profiles["native-release"]["artifact"]["sha256"]:
        raise ValueError("observer and native-release tested different artifact SHA-256 values")
    return {
        "schema_version": 1,
        "case_count": len(cases),
        "pair_count": sum(len(profile["case_ids"]) for profile in profiles.values()),
        "profiles": profiles,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.report_dir / "stabilization-coverage.json"
    try:
        output.unlink(missing_ok=True)
        report = check_coverage(args.report_dir)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, ValueError, csv.Error) as error:
        print(f"stabilization coverage: {error}", file=sys.stderr)
        return 1
    print(f"Verified {report['case_count']} stabilization cases and {report['pair_count']} case/profile pairs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
