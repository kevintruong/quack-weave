#!/usr/bin/env bash
# Run the event's harness against a release built from each exact source revision.
set -euo pipefail
root=$(pwd)
driver="$root/benchmarks/provider_comparison"

measure() {
    local sha=$1 subject=$2 folder=$3 ancestor
    git worktree add --quiet --detach "$subject" "$sha"
    mkdir -p "$subject/build"
    ln -s "$root/build/deps" "$subject/build/deps"
    make -C "$subject" mvp2-deps mvp2-relate-release
    python "$driver/tracker.py" run --source-checkout "$subject" \
        --extension "$subject/build/mvp2-relate/release/extension/quack_weave/quack_weave.duckdb_extension" \
        --fixture "$root/build/perf/provider-comparison/mod1" --library "$DUCKDB_LIB" \
        --out "$subject/build/snapshot.json"
    QW_TRACKER_SNAPSHOT="$subject/build/snapshot.json" "$DUCKDB_UNITTEST" \
        --env-passthrough QW_TRACKER_SNAPSHOT --stdin < "$driver/tracker/snapshot.test" | tee "$subject/build/sqllogic.log"
    # DuckDB can skip a SQLLogic file when a required extension is missing.
    grep -Eq 'All tests passed \([1-9][0-9]+ assertions in 1 test case\)' "$subject/build/sqllogic.log"
    if [[ -n "${PR_BASE_SHA:-}" ]]; then
        ancestor=$(git merge-base "$sha" "$PR_BASE_SHA")
    else
        ancestor=$(git rev-list --parents -n1 "$sha" | cut -s -d' ' -f2)
    fi
    mv "$subject/build/snapshot.json" "$folder/snapshot.json"
    python "$driver/tracker/ci.py" judge "$folder" ${ancestor:+--ancestor "$ancestor"}
}

result=0
scratch=$(mktemp -d "$RUNNER_TEMP/qw-subjects.XXXXXX")
subject="$scratch/source"
# CMake records absolute source paths. Reuse one path across this shard, and
# keep its Cargo output separate from the event checkout's direct clients.
export CARGO_TARGET_DIR="$scratch/target"
trap 'rm -rf -- "$scratch"' EXIT
for sha in "$@"; do
    folder="${QW_EVIDENCE_DIR:-$root/build/ci-evidence}/$sha"
    # A separate errexit-enabled shell keeps failures inside a shard independent.
    set +e
    (set -e; measure "$sha" "$subject" "$folder")
    rc=$?
    set -e
    if [[ $rc != 0 ]]; then
        python - "$folder" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
record = json.loads((p / "record.json").read_text())
if record["status"] == "not_measured":
    (p / "snapshot.json").unlink(missing_ok=True)
    record["status"] = "failed"
    (p / "record.json").write_text(json.dumps(record) + "\n")
PY
        echo "::error::Benchmark failed for $sha"
        result=1
    fi
    if [[ -e "$subject/.git" ]]; then git worktree remove --force "$subject"; fi
done
exit "$result"
