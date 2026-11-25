#!/usr/bin/env bash
# Run the event's harness against a release built from each exact source revision.
set -euo pipefail
root=$(pwd)
driver="$root/benchmarks/provider_comparison"

measure() {
    local sha=$1 folder=$2 ancestor release
    release="$root/build/native/releases/$sha"
    python "$driver/tracker/artifacts.py" verify "$release" "$sha"
    python "$driver/tracker.py" run --source-revision "$sha" \
        --extension "$release/quack_weave.duckdb_extension" \
        --fixture "$root/build/perf/provider-comparison/mod1" --library "$DUCKDB_LIB" \
        --out "$folder/snapshot.json"
    QW_TRACKER_SNAPSHOT="$folder/snapshot.json" "$DUCKDB_UNITTEST" \
        --test-dir "$RUNNER_TEMP" --env-passthrough QW_TRACKER_SNAPSHOT --stdin < "$driver/tracker/snapshot.test" | tee "$RUNNER_TEMP/qw-sqllogic-$sha.log"
    # DuckDB can skip a SQLLogic file when a required extension is missing.
    grep -Eq 'All tests passed \([1-9][0-9]+ assertions in 1 test case\)' "$RUNNER_TEMP/qw-sqllogic-$sha.log"
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
    python "$driver/tracker/ci.py" judge "$folder" ${ancestor:+--ancestor "$ancestor"}
}

result=0
for sha in "$@"; do
    folder="${QW_EVIDENCE_DIR:-$root/build/ci-evidence}/$sha"
    # A separate errexit-enabled shell keeps failures inside a shard independent.
    set +e
    (set -e; measure "$sha" "$folder")
    rc=$?
    set -e
    if [[ $rc != 0 ]]; then
        python - "$folder" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
record = json.loads((p / "record.json").read_text())
if record["status"] == "regression":
    series = ", ".join(r["series"] for r in record["regressions"])
    print(f"::error::Latency gate for {p.name} flagged {series}. See the run summary for timings.")
else:
    print(f"::error::Benchmark measurement or verification failed for {p.name}")
if record["status"] == "not_measured":
    (p / "snapshot.json").unlink(missing_ok=True)
    record["status"] = "failed"
    (p / "record.json").write_text(json.dumps(record) + "\n")
PY
        result=1
    fi
done
exit "$result"
