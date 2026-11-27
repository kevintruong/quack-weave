#!/usr/bin/env bash
# Run the event's harness against a release built from each exact source revision.
set -euo pipefail
root=$(pwd)
driver="$root/benchmarks/provider_comparison"

check_sqllogic_log() {
    # DuckDB can skip a SQLLogic file when a required extension is missing.
    grep -Eq 'All tests passed \([1-9][0-9]* assertions? in 1 test case\)' "$1"
}

verify_snapshot() {
    local snapshot=$1 log=$2
    QW_TRACKER_SNAPSHOT="$snapshot" "$DUCKDB_UNITTEST" \
        --test-dir "$RUNNER_TEMP" --env-passthrough QW_TRACKER_SNAPSHOT --stdin < "$driver/tracker/snapshot.test" | tee "$log"
    check_sqllogic_log "$log"
}

measure() {
    local sha=$1 folder=$2 scratch=$3 ancestor release archived
    local artifact_token=${QW_ARTIFACT_TOKEN:-${GH_TOKEN:-}}
    unset QW_ARTIFACT_TOKEN GH_TOKEN
    release="$root/build/native/releases/$sha"
    python "$driver/tracker/artifacts.py" verify "$release" "$sha"
    local -a args=(--source-revision "$sha" --extension "$release/quack_weave.duckdb_extension"
        --fixture "$root/build/perf/provider-comparison/mod1" --library "$DUCKDB_LIB")
    if [[ -n "${PR_BASE_SHA:-}" ]]; then
        ancestor=$(git merge-base "$sha" "$PR_BASE_SHA")
    else
        ancestor=$(git rev-list --parents -n1 "$sha" | cut -s -d' ' -f2)
    fi
    if [[ "$sha" == "${SOURCE_HEAD:-}" ]]; then
        export QW_RELEASE_ARTIFACT_ID="${HEAD_ARTIFACT_ID:-}"
    else
        export QW_RELEASE_ARTIFACT_ID="${HISTORICAL_ARTIFACT_ID:-}"
    fi
    python "$driver/tracker.py" run "${args[@]}" --describe "$scratch/description.json"
    GH_TOKEN="$artifact_token" python "$driver/tracker/ci.py" select "$scratch/description.json" \
        "$scratch/selection.json" ${ancestor:+--ancestor "$ancestor"}
    archived=$(jq -r '.baseline_sha // empty' "$scratch/selection.json")
    if [[ -n "$archived" ]]; then
        args+=(--baseline-revision "$archived" --baseline-extension "$(jq -er .extension "$scratch/selection.json")"
            --baseline-out "$folder/baseline.json")
    fi
    python "$driver/tracker.py" run "${args[@]}" --out "$folder/snapshot.json"
    verify_snapshot "$folder/snapshot.json" "$scratch/candidate.log"
    if [[ -n "$archived" ]]; then
        verify_snapshot "$folder/baseline.json" "$scratch/baseline.log"
        QW_TRACKER_SNAPSHOT="$folder/snapshot.json" QW_TRACKER_BASELINE="$folder/baseline.json" "$DUCKDB_UNITTEST" \
            --test-dir "$RUNNER_TEMP" --env-passthrough QW_TRACKER_SNAPSHOT --env-passthrough QW_TRACKER_BASELINE \
            --stdin < "$driver/tracker/pair.test" | tee "$scratch/pair.log"
        check_sqllogic_log "$scratch/pair.log"
    fi
    if [[ "$sha" == "${SOURCE_HEAD:-}" ]]; then
        local hybrid_fixture="$root/build/perf/provider-comparison/mod32"
        echo "86ee28c86fbc633d3f354721c7778ff404ccf41370d9a74b567717a78c2e9e0b  $hybrid_fixture/edges.csv" | shasum -a 256 --check
        python "$driver/tracker.py" run --source-revision "$sha" --extension "$release/quack_weave.duckdb_extension" \
            --fixture "$hybrid_fixture" --library "$DUCKDB_LIB" \
            --duckdb-unittest "$DUCKDB_UNITTEST" --micro --case micro_creator_selective \
            --blocks 2 --runs 2 --out "$scratch/hybrid.json"
        python - "$driver/tracker" "$folder/snapshot.json" "$scratch/hybrid.json" <<'PY_ATTACH'
import json
from pathlib import Path
import sys

sys.path.insert(0, sys.argv[1])
from archive import validate_hybrid_snapshot

snapshot_file, hybrid_file = map(Path, sys.argv[2:])
snapshot, hybrid = (json.loads(path.read_text()) for path in (snapshot_file, hybrid_file))
validate_hybrid_snapshot(snapshot, hybrid)
snapshot["hybrid_smoke_snapshot"] = hybrid
snapshot_file.write_text(json.dumps(snapshot, indent=2, allow_nan=False) + "\n")
PY_ATTACH
    fi
    python "$driver/tracker/ci.py" judge "$folder" --selection "$scratch/selection.json"
}

result=0
for sha in "$@"; do
    folder="${QW_EVIDENCE_DIR:-$root/build/ci-evidence}/$sha"
    scratch=$(mktemp -d "$RUNNER_TEMP/qw-pair.XXXXXX")
    # A separate errexit-enabled shell keeps failures inside a shard independent.
    set +e
    (set -e; measure "$sha" "$folder" "$scratch")
    rc=$?
    set -e
    rm -rf -- "$scratch"
    if [[ $rc != 0 ]]; then
        python - "$folder" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
print(f"::error::Benchmark measurement or verification failed for {p.name}")
for snapshot in ("snapshot.json", "baseline.json"):
    (p / snapshot).unlink(missing_ok=True)
(p / "record.json").write_text(json.dumps({"commit": p.name, "status": "failed"}) + "\n")
PY
        result=1
    fi
done
exit "$result"
