# Standalone and hybrid graph benchmark tracker

Use this tracker to measure the client-visible cost of submitting a graph query through QuackWeave, and to follow hybrid SQL performance between releases. The unit of comparison is one provider, one execution route, and one workload on the same frozen graph. [Runner](../tracker.py) · [SF1 observations](sf1.json)

| Workloads | QuackWeave route | Reference |
|---|---|---|
| Indexed person lookup, lookup with no match, message-creator fanout | Bare GQL and bare Cypher, measured independently | The identical statement through the same provider's native Cypher client |
| Graph-local equality, outer SQL equality, equality through a view | DuckDB SQL with `GRAPH_TABLE` | CSV result oracle and prior QuackWeave snapshots |
| Literal watchlist join, DuckDB table watchlist join, full count and checksum | DuckDB SQL with `GRAPH_TABLE` | CSV result oracle and prior QuackWeave snapshots |

### Full SF1 baseline

The November 25, 2026 run used the 3,809,607-edge creator projection and release binary `a4cb4aa8b23d` on macOS arm64. All 30 series completed, yielding 600 verified hot observations across four alternating blocks. The tables give warm p50 times in milliseconds. The snapshot also contains p95, per-process setup and RSS, and every individual timing. [Raw snapshot](sf1.json)

| Provider | Standalone workload | Direct Cypher | QuackWeave Cypher | QuackWeave GQL |
|---|---|---:|---:|---:|
| Ladybug | Lookup hit | 0.901 | 0.565 | 2.438 |
| Ladybug | Lookup miss | 0.096 | 0.564 | 2.594 |
| Ladybug | Fanout, 6,465 messages | 2.804 | 2.868 | 5.169 |
| RelateDB | Lookup hit | 0.050 | 0.573 | 2.374 |
| RelateDB | Lookup miss | 0.050 | 0.553 | 2.767 |
| RelateDB | Fanout, 6,465 messages | 5.616 | 5.738 | 8.156 |

On this run QuackWeave Cypher fanout was within 3% of each direct client's median. The RelateDB native point lookup took about 50 microseconds, so even a sub-millisecond QuackWeave Cypher lookup was over 11 times its direct latency.

| Hybrid workload through QuackWeave | Ladybug | RelateDB | Graph rows delivered on each provider |
|---|---:|---:|---:|
| Graph-local equality | 4.000 | 6.967 | 6,465 |
| Outer SQL equality | 4.108 | 7.043 | 6,465 |
| Equality through a view | 4.507 | 7.374 | 6,465 |
| Literal watchlist join | 9.515 | 51.253 | 23,316 |
| DuckDB table watchlist join | 9.486 | 51.496 | 23,316 |
| Full scalar aggregate | 109.917 | 3,008.493 | 1 |

### Measurement

DuckDB's benchmark runner initializes state before the timing loop, executes one warmup, repeats the operation, and verifies results after timing. We followed `BenchmarkRunner::RunBenchmark` and `DuckDBBenchmark::Verify` with `code_symbol_search` and `code_read_symbol` on the registered DuckDB project and checked the lifecycle against the pinned DuckDB 2.0.1 source. [DuckDB benchmark runner](https://github.com/duckdb/duckdb/blob/8d78114e90a53823803660bf821f6073ac87da8c/benchmark/benchmark_runner.cpp#L127-L194) · [DuckDB verification hook](https://github.com/duckdb/duckdb/blob/8d78114e90a53823803660bf821f6073ac87da8c/benchmark/include/duckdb_benchmark.hpp#L118-L121)

Each route starts a fresh process and opens a read-only graph once per block. Blocks alternate provider and route order. The same deterministic shuffle orders the standalone queries across GQL, Cypher and direct clients. Each case gets one warmup and five measured executions per block by default. Four blocks give 20 warm observations per series. P50 is the median and p95 is nearest-rank. Repetition zero contains the warmup. Filesystem caches stay enabled.

QuackWeave uses the DuckDB ADBC driver and fetches the whole Arrow table. Direct Ladybug uses the 0.22.3 Python client and fetches the whole Arrow table. Direct RelateDB uses the embedded 1.2.0 Rust API and collects the returned integer IDs into a vector. The Rust worker times the call internally, before sending results to the verifier. These timings include each client's result materialization. The wall-clock ratio therefore measures the two client paths and includes their different result formats. [Direct RelateDB worker](../../../crates/native/examples/relate_bench_read.rs)

Every execution, including warmup, must match a sorted row-count and SHA-256 signature derived from the fixture CSV. Sorting retains duplicate rows. The tracker checks the CSV and both provider file hashes before and after each run. It records CPU time per sample, open or registration time, DuckDB load time, and peak worker-process RSS. The latter includes the client runtime and all cases sharing that worker. After timing, hybrid workers record rows delivered by the graph scan using `EXPLAIN (ANALYZE, FORMAT JSON)`. A timeout, incorrect result, or worker error exits with failure before publishing a snapshot.

### Run

Provision the pinned combined extension, Python environment and creator projection using the provider comparison instructions. The default fixture is the full `mod1` snapshot. Use `--fixture build/perf/provider-comparison/mod256` for a quick run. Build the dedicated native reader from the repository root. [Fixture and dependency setup](../README.md)

```sh
cargo build --locked -p rusty_quack --target aarch64-apple-darwin --release \
  --features relate-provider --target-dir target/mvp2-relate --example relate_bench_read
py=build/usage-client-venv/bin/python
tracker=benchmarks/provider_comparison/tracker.py
"$py" -B "$tracker" list
"$py" -B "$tracker" run
```

The default output is a timestamped JSON file under `build/perf/provider-comparison/tracker/`. Use `--out` to choose a new filename. Existing snapshots are protected from replacement. Repeat `--case` or `--provider` for a focused run. For example, `--case fanout --provider relate` exercises all three standalone routes, while `--case table_watchlist` exercises the two QuackWeave hybrid routes.

### Track changes

```sh
"$py" -B "$tracker" compare benchmarks/provider_comparison/tracker/sf1.json path/to/new.json
```

The comparison prints old/new p50 and p95 and percentage change in median latency. A positive change means slower. It checks the host, fixture, SQL, expected answers, sample counts and route matrix for compatibility. Snapshots record the release binary hashes, DuckDB and provider versions, tracker source hash and workspace revision. A ratio of 1.5 in `qw_over_direct` means the QuackWeave median took 1.5 times the direct median for that workload on that provider.

The SQL macro reads a snapshot file, a glob, or a list of files. Point it at snapshots from the same machine, fixture and protocol when comparing timings. This query displays the most recent runs for the table-backed watchlist.

```sql
.read benchmarks/provider_comparison/tracker/history.sql
SELECT started_utc, provider, p50_ms, p95_ms, n
FROM qw_benchmark_history('build/perf/provider-comparison/tracker/*.json')
WHERE workload = 'table_watchlist'
ORDER BY started_utc DESC, provider;
```

Run the snapshot SQLLogic test against a complete matrix to independently recalculate the percentiles and native ratios from raw observations and check the hybrid scan counts.

```sh
QW_TRACKER_SNAPSHOT="$PWD/benchmarks/provider_comparison/tracker/sf1.json" \
  build/stabilization-runner-v2.0.1/unittest --env-passthrough QW_TRACKER_SNAPSHOT \
  --stdin < benchmarks/provider_comparison/tracker/snapshot.test
```

### GitHub Actions and commit history

The **Benchmark tracker** workflow runs on every push to `main` and every opened, reopened or updated pull request, including documentation changes. It measures the actual extension built from each introduced Git commit. On a PR it uses the source commit. If GitHub no longer serves a force-pushed previous tip, the tracker includes the full reachable range. Multi-commit events are split across up to 32 macOS arm64 jobs, and new pushes keep earlier runs active. Each job uses the event head's benchmark harness and direct clients, plus the same checksummed full SF1 fixture. [Measurement workflow](../../../.github/workflows/Benchmark.yml)

The **Benchmark tracker gate** fails on build errors, incorrect query results, SQLLogic failures, and latency regressions. For each of the 30 series the default regression threshold requires both p50 and p95 to increase by at least 20%, with a p50 increase of at least 0.25 ms. The Actions summary gives the baseline commit, affected series and timings. Repository variables `QW_REGRESSION_PERCENT` and `QW_REGRESSION_FLOOR_MS` override the thresholds. To require a passing benchmark before merging, select **Benchmark tracker gate** in the branch ruleset for `main` after the workflow first runs.

The comparison walks first-parent main ancestry, starting at the commit's first parent for pushes and its merge base with the PR target for pull requests. It uses the newest successful, compatible attempt on the nearest recorded ancestor. Compatibility includes hardware, OS, client versions, logical graph checksum, workload statements, expected answers and sampling protocol. A fresh cohort records a verified `baseline` with no performance verdict. Concurrent runs compare against the history available when their shard starts.

After the benchmark finishes, **Archive benchmark history** reads the run artifacts and appends JSON to the `benchmark-history` branch. Each attempt has its own directory, including PR runs from forks. A repeat publication preserves identical evidence and rejects conflicting content. Concurrent publications retry fast-forward pushes. Only main results with status `baseline` or `passed` can serve as future baselines. The commit manifest lets the publisher record a missing shard as `not_measured`. Failed measurements retain their status. Regressions retain the full snapshot, the applied thresholds and the baseline SHA. The archive remains queryable after the 30-day Actions artifacts expire. [Archive workflow](../../../.github/workflows/BenchmarkHistory.yml)

```text
main/<commit-sha>/<actions-run-id>-<attempt>/record.json
main/<commit-sha>/<actions-run-id>-<attempt>/snapshot.json
pull_request/<commit-sha>/<actions-run-id>-<attempt>/record.json
pull_request/<commit-sha>/<actions-run-id>-<attempt>/snapshot.json
```

The read-only measurement jobs build repository code. The publisher runs the default branch's archive script with permission to write the history branch. It accepts bounded JSON files under validated commit paths. Both workflows must be installed on the default branch, and repository policies must permit the Actions token to write `benchmark-history`. [GitHub workflow completion events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run)

To inspect the archive locally, run the following after the first Actions publication.

```sh
git fetch origin benchmark-history
git worktree add --detach ../qw-benchmark-history origin/benchmark-history
```

```sql
.read benchmarks/provider_comparison/tracker/history.sql
SELECT workspace_head, started_utc, provider, workload, p50_ms, p95_ms
FROM qw_benchmark_history('../qw-benchmark-history/main/*/*/snapshot.json')
WHERE workload IN ('table_watchlist', 'full_scan_aggregate')
ORDER BY started_utc DESC, provider, workload;
```

Jev compiled the archive-key constraint with `data_integrity.unique`. Z3 accepted the commit/run/attempt key and found a collision when the attempt was removed. The workflow also runs integration tests against temporary Git remotes for multi-commit updates, concurrent writers, retries, rejected overwrites, and baseline selection.

```sh
python3 -B -m unittest discover -s benchmarks/provider_comparison/tracker -p 'test_ci.py'
```
