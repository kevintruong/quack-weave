# Run the Hybrid Query test bench

Use the native SQLLogic suite for correctness and the provider tracker for performance. The tiny `micro_creator_selective` fixture exercises duplicate and NULL keys. The scaled `mod32` replay runs the same versioned SQL on Ladybug and RelateDB with graph prefiltering enabled and disabled.

## Set up the host and fixture

Run these commands from the repository root on Apple Silicon macOS or Linux ARM64. Use a QuackWeave release built against DuckDB 2.0.1 with the Ladybug and RelateDB adapters. If you already have a compatible release and DuckDB host, point the variables below at those artifacts and reuse them.

```sh
python3.12 -m venv build/tracker-venv
tracker_python=build/tracker-venv/bin/python
"$tracker_python" -m pip install --only-binary=:all: --require-hashes \
  -r benchmarks/provider_comparison/tracker/requirements.txt
"$tracker_python" benchmarks/provider_comparison/tracker/install_host.py
make native-deps native-release

export DUCKDB_UNITTEST="$PWD/build/benchmark-host/unittest"
case "$(uname -s)" in
  Darwin) export DUCKDB_LIB="$PWD/build/benchmark-host/release/src/libduckdb.dylib" ;;
  Linux)  export DUCKDB_LIB="$PWD/build/benchmark-host/release/src/libduckdb.so" ;;
esac
export QW_EXT="$PWD/build/native/release/extension/quack_weave/quack_weave.duckdb_extension"
export LBUG="$PWD/build/deps/ladybug-v0.22.3/lbug"
```

The host installer uses `gh` to retrieve a pinned GitHub release artifact when it is absent from the cache. For the scaled fixture, place the [pinned LSQB SF1 graph](../benchmarks/lsqb_sf1/watchlist.py) at `build/perf/lsqb-sf1/sf1.lbdb`, then run the preparation command below. The builder checks the source hash and creates both provider files, the shared edge CSV, and a fixture manifest.

```sh
"$tracker_python" -B benchmarks/provider_comparison/prepare.py --modulus 32 \
  --source build/perf/lsqb-sf1/sf1.lbdb
```

## Verify correctness with native SQLLogic

The stabilization runner provisions fresh graph files and executes the tiny shared-workload witness with the rest of the native SQLLogic suite. Look for `hybrid_creator_selective.test` and its `[QW_HYBRID_WORKLOAD]` receipt. The witness checks the output schema, compares both routes to an independent relational oracle, and checks the applied optimized route.

```sh
python3 -B test/stabilization/run_sqllogictest.py \
  --duckdb-unittest "$DUCKDB_UNITTEST" --extension "$QW_EXT" --lbug "$LBUG"
```

The [workload manifest](../benchmarks/provider_comparison/hybrid_workloads.json) maps cases to the shared SQL template, oracle, and SQLLogic files. The provider suite also covers [applied watchlist routes](../test/relate/watchlist_applied_route.test) and [ordered LIMIT behavior](../test/relate/ordered_watchlist_limit.test).

## Choose a suite

| Command | Workload |
| --- | --- |
| `run --micro --case micro_creator_selective` | Release smoke with one selective creator join. |
| `run --micro` | All four endpoint join shapes adapted from CM-LDBC. |
| `run --hybrid` | All four application workloads below. |

Both suites default to `mod32`. Run `tracker.py list` for case names and supported arms. Repeat `--case` to select a subset or use `--provider ladybug` or `--provider relate` to focus on one provider.

| Application case | What it checks |
| --- | --- |
| `directory_join_topk` | Rank after the Parquet directory join. The native witness uses airport routes. The scaled replay uses the SF1 creator projection. |
| `prepared_watchlist_churn` | Reuse one prepared statement with 63, 64, and 65 distinct keys. The timed sample includes all replacements and fetches. Find per-epoch rows, offers, and applied routes in `scan_diagnostics.steps`. |
| `creator_sales_top_channels` | Rank seven- and 30-day settled sales from a seeded Parquet ledger. The `qw_sql_staged` arm captures the portfolio once through Arrow. Its transfer is included in `setup.application_setup_ms`. |
| `two_hop_enriched` | Join sibling message paths to SQL attributes and preserve path multiplicity. Its explicit Cypher read records scan and admission metrics under either watchlist setting. |

## Replay and compare

This smoke run uses two matched blocks and two measured calls per block for each provider and route. Each block first runs a verified warmup. Each run gets its own output file.

```sh
tracker=benchmarks/provider_comparison/tracker.py
qw_replays=$(mktemp -d "${TMPDIR:-/tmp}/qw-hybrid.XXXXXX")

run_replay() {
  snapshot_name=$1
  shift
  "$tracker_python" -B "$tracker" run "$@" \
    --fixture build/perf/provider-comparison/mod32 \
    --extension "$QW_EXT" --library "$DUCKDB_LIB" \
    --duckdb-unittest "$DUCKDB_UNITTEST" --blocks 2 --runs 2 \
    --out "$qw_replays/$snapshot_name.json"
}

run_replay first --micro --case micro_creator_selective &&
  run_replay second --micro --case micro_creator_selective &&
  "$tracker_python" -B "$tracker" compare "$qw_replays/first.json" "$qw_replays/second.json"
```

Use `--hybrid` in both replay calls for the application suite. The `qw_pgq` arm enables the watchlist prefilter. The `qw_pgq_host` arm disables it. Check `scan_diagnostics.applied_route` for the route actually taken. Both arms must produce the exact oracle result. A failed result or SQLLogic check prevents snapshot publication.

The two snapshots should agree on `workload_evidence`, `schedule_sha256`, the result signature, and the SQLLogic receipts. The comparison prints warm p50 and p95 from verified full fetches. Use more matched samples before interpreting the tails. For a release-to-release comparison, use the same `run` command with `--source-revision`, plus `--baseline-extension`, `--baseline-revision`, and a fresh `--baseline-out`. The tracker alternates release order within the run.

## Inspect metrics and archived evidence

Load the metric view from the DuckDB CLI and substitute the actual path to the first snapshot or an archived `hybrid_snapshot.json`.

```sql
.read benchmarks/provider_comparison/tracker/history.sql
SELECT provider, route, block, repetition, metric_id, unit,
       numeric_value, count_value, text_value
FROM qw_benchmark_metrics('/path/to/first.json')
WHERE workload = 'micro_creator_selective'
ORDER BY provider, route, block, repetition, metric_id;
```

- `first_fetch` is the verified warmup. `release_wall` measures the subsequent calls through full Arrow fetch.
- `scan_rows` counts graph rows crossing into DuckDB before the residual SQL operators. `result_rows` counts the final SQL rows.
- `applied_route` and `admitted_generation` come from an untimed diagnostic replay. Optional provider timing appears when captured.

The CI smoke uses the pinned `mod32` fixture. The history publisher exposes its verified snapshot as `hybrid_snapshot.json` alongside the standard benchmark snapshot for the same attempt. See the [tracker reference](../benchmarks/provider_comparison/tracker/README.md) for setup, comparison, and history details.
