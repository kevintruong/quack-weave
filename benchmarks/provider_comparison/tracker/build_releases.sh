#!/usr/bin/env bash
# Build historical revisions using the workflow revision's staging contract.
set -euo pipefail
root=$PWD
scratch=$(mktemp -d "$RUNNER_TEMP/qw-build.XXXXXX")
subject="$scratch/source"
export CARGO_TARGET_DIR="$scratch/target"
# Called by the EXIT trap on failure as well as normal completion.
# shellcheck disable=SC2329
cleanup() {
    if [[ -e "$subject/.git" ]]; then git worktree remove --force "$subject"; fi
    rm -rf -- "$scratch"
}
trap cleanup EXIT
failed=0
for sha in "$@"; do
    if [[ "$sha" == "$SOURCE_HEAD" ]]; then continue; fi
    git worktree add --quiet --detach "$subject" "$sha"
    mkdir -p "$subject/build"
    ln -s "$root/build/deps" "$subject/build/deps"
    if make -C "$subject" mvp2-deps mvp2-relate-release; then
        python3 "$root/benchmarks/provider_comparison/tracker/artifacts.py" stage "$subject" "$root/build/historical"
    else
        # The consumer marks this SHA failed and still measures the other releases.
        echo "::error::Could not build release $sha"
        failed=1
    fi
    git worktree remove --force "$subject"
done
exit "$failed"
