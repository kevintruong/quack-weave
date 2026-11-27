# Standalone and hybrid graph benchmark tracker

Use this tracker to measure the client-visible cost of submitting a graph query through QuackWeave, and to follow hybrid SQL performance between releases. The unit of comparison is one provider, one execution route, and one workload on the same frozen graph. [Runner](../tracker.py) · [SF1 observations](sf1.json)

| Workloads | QuackWeave route | Reference |
|---|---|---|
| Indexed person lookup, lookup with no match, message-creator fanout | Bare GQL and bare Cypher, measured independently | The identical statement through the same provider's native Cypher client |
| Graph-local equality, outer SQL equality, equality through a view | DuckDB SQL with `GRAPH_TABLE` | CSV result oracle and prior QuackWeave snapshots |
| Literal watchlist join, DuckDB table watchlist join, full count and checksum | DuckDB SQL with `GRAPH_TABLE` | CSV result oracle and prior QuackWeave snapshots |

### View CI benchmark tables

Open a **CI** run and select **Summary**. The standalone and hybrid tables show median (p50) and p95 latency in milliseconds. In paired reports, each percentile shows a signed change from the baseline. Negative changes are faster. Positive changes below 10% are acceptable. An increase of 10% or more appears in bold as a regression, and the summary lists the affected workload and percentile. A workload can improve at p50 and regress at p95. The standalone ratio compares each QuackWeave median to the same provider's direct Cypher median. [CI runs](https://github.com/kevintruong/quack-weave/actions/workflows/CI.yml)

The `benchmark-history` branch displays the latest published main run on its front page. For an individual commit, open `main/<commit>/<run>-<attempt>/` or `pull_request/<commit>/<run>-<attempt>/`. Each new attempt has a rendered README beside its JSON evidence. PRs and late-finishing older runs preserve the latest main report. [Latest main report](https://github.com/kevintruong/quack-weave/tree/benchmark-history)

To display an earlier attempt, download its `qw-benchmark-…` artifact or open a local checkout of the archive, then render the folder containing `record.json`.

```sh
python3 benchmarks/provider_comparison/tracker/ci.py report path/to/attempt > benchmark.md
```

### Full SF1 baseline

The historical protocol 1 run on November 25, 2026 used the 3,809,607-edge creator projection and release binary `a4cb4aa8b23d` on macOS arm64. All 30 series completed, yielding 600 verified hot observations across four alternating blocks. The tables give warm p50 times in milliseconds. The snapshot also contains p95, per-process setup and RSS, and every individual timing. [Raw snapshot](sf1.json)

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

QuackWeave uses the DuckDB ADBC driver and fetches the whole Arrow table. Direct Ladybug uses the 0.22.3 Python client and fetches the whole Arrow table. Direct RelateDB uses the official 1.2.0 Python wheel, opens the bundle read-only and materializes the Arrow IPC result. Protocol 2 includes materialization time on all three paths. The change from the protocol 1 Rust reader starts a new timing cohort. [Tracker](../tracker.py)

Every execution, including warmup, must match a sorted row-count and SHA-256 signature derived from the fixture CSV. Sorting retains duplicate rows. The tracker checks the CSV and both provider file hashes before and after each run. It records CPU time per sample, open or registration time, DuckDB load time, and peak worker-process RSS. The latter includes the client runtime and all cases sharing that worker. After timing, hybrid workers record rows delivered by the graph scan using `EXPLAIN (ANALYZE, FORMAT JSON)`. A timeout, incorrect result, or worker error exits with failure before publishing a snapshot.

### Run

Use native Linux arm64 or macOS arm64 with Python 3.12. Minimal Ubuntu containers need the distribution's `libatomic1` runtime for DuckDB SQLLogic. Run `gh auth login` if the local GitHub CLI has no session. The build produces the QuackWeave extension under test. DuckDB supplies its compiled SQLLogic executable and the matching library containing the ADBC driver. PyPI supplies the pinned graph clients, ADBC manager and Arrow wheels. The default fixture is the full `mod1` projection. Pass `--fixture build/perf/provider-comparison/mod256` for a small run. [Fixture setup](../README.md)

```sh
python3.12 -m venv build/tracker-venv
py=build/tracker-venv/bin/python
"$py" -m pip install --only-binary=:all: --require-hashes -r benchmarks/provider_comparison/tracker/requirements.txt
"$py" benchmarks/provider_comparison/tracker/install_host.py
tracker=benchmarks/provider_comparison/tracker.py
"$py" -B "$tracker" run
```

The default output is a timestamped JSON file under `build/perf/provider-comparison/tracker/`. Use `--out` to choose a new filename. Existing snapshots are protected from replacement. Repeat `--case` or `--provider` for a focused run. For example, `--case fanout --provider relate` exercises all three standalone routes, while `--case table_watchlist` exercises the two QuackWeave hybrid routes.

### Prepared lookups

Pass `--include-prepared` to compare a reused `qw_query` statement with bare Cypher and GQL and the direct graph client. The prepared route fixes the graph alias, dialect, graph query and output schema. The ADBC worker uses one cursor per statement on the same DuckDB connection. It records preparation under `setup.prepare_ms` and times execution through the full Arrow fetch. All routes use the same graph result checks. The snapshot records the exact prepared SQL under `prepared_statements`. [Public client pattern](../../../README.md#explicit-schema-bridge)

```sh
"$py" -B "$tracker" run --include-prepared --case lookup --case lookup_miss
```

### CM-LDBC workloads

`--micro` adapts MICRO's CM-LDBC split between graph topology and relational attributes to the matched LSQB SF1 creator projection. The suite uses its own creator and message relations with matching IDs, synthetic misses, duplicate rows and NULL keys. It exercises four query shapes from that design on DuckDB and the two local graph providers. [MICRO CM-LDBC design](https://arxiv.org/html/2603.13835v1#S7.SS2) · [Pinned upstream benchmark](https://github.com/xiz675/MICRO/tree/ec0e5ab51e2b7899e8048ced8efe33992f06d394/benchmark)

| Workload | Join shape |
| --- | --- |
| `micro_creator_selective` | Join creator attributes with a selective tier predicate and group by segment. |
| `micro_creator_broad` | Join the larger creator relation without the tier filter. Its 65 matching keys exceed the QuackWeave cap. |
| `micro_message_selective` | Join attributes on the message endpoint and group by topic. |
| `micro_creator_message` | Join both endpoints to their relations and group by segment and topic. |

The suite defaults to `mod32` and measures both `qw_pgq` and `qw_pgq_host` with the same SQL and DuckDB optimizer. `qw_pgq_host` disables only QuackWeave's runtime watchlist prefilter. Both routes use a DuckDB key-offer threshold of 128. Use an extension with `qw_enable_runtime_watchlist`. Use `--provider` or `--case` to focus a run.

```sh
tracker=benchmarks/provider_comparison/tracker.py
"$py" -B "$tracker" run --micro \
  --extension build/native/release/extension/quack_weave/quack_weave.duckdb_extension \
  --duckdb-unittest build/benchmark-host/unittest \
  --out build/perf/provider-comparison/tracker/micro-snapshot.json
```

The tracker checks every fetch against the CSV oracle. Before publishing an immutable snapshot, it runs the actual workload SQL through SQLLogic on both routes, then independently recomputes p50, p95, and sample counts from the saved timing rows. The snapshot records fixture and binary hashes, the relational input rows, SQLLogic source hashes and rows delivered from the provider. Rerun with a fresh output path, then use `tracker.py compare` with the two snapshots. The standard suite and its CI workload matrix use the existing default selection.

### Replay evidence and metric history

The [workload manifest](../hybrid_workloads.json) pins the case revision, SQL template and oracle. `micro_creator_selective` uses the same SQL in the tiny native stabilization witness and the scaled tracker. The fixtures are independent instances. MICRO snapshots retain their case, fixture, parameter, SQL and result digests, plus the planned schedule and verified call receipts. A run publishes after SQLLogic checks those receipts against the observed sample order and oracle.

The benchmark workflow runs a source-head MICRO smoke replay with the checksummed SF1 mod32 fixture and the same release. The history publisher exposes it as `hybrid_snapshot.json` beside the ordinary snapshot. Use the raw metric view with that file or a local tracker snapshot.

```sql
.read benchmarks/provider_comparison/tracker/history.sql
SELECT provider, route, block, repetition, metric_id, unit, numeric_value, count_value, text_value
FROM qw_benchmark_metrics('path/to/hybrid_snapshot.json')
WHERE workload = 'micro_creator_selective'
ORDER BY provider, route, block, repetition, metric_id;
```

`first_fetch` is the verified warmup on each worker and case. `release_wall` covers the later full client fetches. The scan diagnostics come from a separate untimed query. Optional provider timing and route evidence appear when captured by the measured artifact.

### Track changes

```sh
"$py" -B "$tracker" compare path/to/protocol-2-baseline.json path/to/new.json
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

Run the snapshot SQLLogic test against the complete CI matrix to independently recalculate the percentiles and native ratios from raw observations and check the hybrid scan counts.

```sh
QW_TRACKER_SNAPSHOT="$PWD/benchmarks/provider_comparison/tracker/sf1.json" \
  build/benchmark-host/unittest --test-dir "${TMPDIR:-/tmp}" --env-passthrough QW_TRACKER_SNAPSHOT \
  --stdin < benchmarks/provider_comparison/tracker/snapshot.test
```

### GitHub Actions and commit history

The **CI** workflow plans one measurement for every commit introduced by a push to `main` or an opened, reopened or updated PR, including documentation changes. A force push with an unavailable previous tip includes the full reachable range. Up to 32 shards run independently. Each shard uses the workflow revision's harness, the same hash-locked upstream clients, and the same checksummed SF1 graph. PRs also run Rust checks and stabilization. A main push builds only the native inputs needed by the tracker in this workflow. [CI workflow](../../../.github/workflows/CI.yml) · [Benchmark jobs](../../../.github/workflows/Benchmark.yml)

| Build output | Revision and configuration | Consumers |
|---|---|---|
| DuckDB SQLLogic runner and ADBC library | DuckDB 2.0.1 release-build artifact for the selected ARM64 platform | Native stabilization, provider integration and all benchmark shards |
| Stabilization packages, licenses and Rust observer test executables | CI checkout, including the merge revision on PRs. Native debug and release | Stabilization and public-client tests |
| Native release and RelateDB fixture builder | PR source head or main push tip, `native-release` | Provider integration and SF1 measurements use the same extension bytes. |
| Earlier releases with RelateDB | One release per additional source SHA in a multi-commit event | The corresponding commit's SF1 measurement |

The planner selects GitHub's `ubuntu-24.04-arm` for commits with a Linux build target. An event containing an older macOS-only commit runs its entire comparison on `macos-15`. Hardware, platform and protocol are part of baseline selection. The measurement job consumes the compiled QuackWeave artifact for each SHA and installs the pinned standalone clients. RelateDB's embedded Rust crate is part of the extension build.

The DuckDB 2.0.1 SQLLogic runner comes from upstream Actions run `44520268851`. Its original artifacts expire on **2027-02-17**. Cache misses require authenticated GitHub CLI access to the public artifacts or an HTTPS mirror of the two original archives. Set the repository variable `QW_DUCKDB_BUILD_MIRROR` to the mirror's base URL before upstream expiry. The installer verifies the original SHA-256 on every use and fails if the pinned bytes are unavailable. [Upstream build](https://github.com/duckdb/duckdb/actions/runs/44520268851) · [Artifact names and hashes](install_host.py) · [Wheel versions and hashes](requirements.txt)

For the candidate, consumers download the producing job's artifact by ID within the same workflow run. For the baseline, the benchmark downloads the release artifact recorded in the selected main commit's snapshot. It verifies the commit, native profile and extension SHA-256 against the manifest, and checks the baseline digest against the original measurement. The snapshot retains the artifact IDs and binary hashes alongside the timings.

The **Benchmark tracker gate** passes when the build, measurements, query results, artifact checks and SQLLogic verification succeed. Latency changes are advisory. For each paired series the tracker evaluates p50 and p95 independently against their respective baseline timings, using the unrounded percentage and a fixed 10% slowdown threshold. A flagged measurement produces a GitHub Actions warning. Build errors, invalid results, failed verification and incomplete measurements still fail CI. To require successful benchmark verification before merging, select **Benchmark tracker gate** in the branch ruleset for `main`.

The comparison walks first-parent main ancestry, starting at the commit's first parent for pushes and its merge base with the PR target for pull requests. It selects the nearest compatible ancestor with a retained release, trying successful attempts from newest to oldest. Compatibility includes hardware, OS, client versions, logical graph checksum, workload statements, expected answers and sampling protocol. Concurrent runs select from the history available when their shard starts.

The tracker times both extensions on the **same VM** against the same graph files and installed clients. The baseline goes first in even-numbered blocks (starting at zero) and the candidate goes first in odd-numbered blocks. Each release gets its own fresh worker processes and warmups. The report compares the two sets of fresh timings. Both snapshots record the shared pair ID, VM identifier and execution order. SQLLogic checks each full matrix and the pairing.

A first measurement records a `baseline`. If all compatible releases are unavailable, the report names the nearest compatible ancestor and records a new baseline with no latency verdict. Download errors and digest mismatches fail the measurement. The Actions summary and archived report show both releases' p50 and p95 for every paired workload.

After the benchmark finishes, **Archive benchmark history** appends JSON to the `benchmark-history` branch. Each attempt has its own directory, including PR runs from forks. A repeat publication preserves identical evidence and rejects conflicting content. Concurrent publications retry fast-forward pushes. Verified main results with status `baseline` or `passed` can serve as future baselines, including passes with timing warnings. Paired records retain the review threshold, baseline SHA and per-percentile findings under `regressions` and `improvements`. Older records retain their original verdict and thresholds. The commit manifest lets the publisher record a missing shard as `not_measured`. The archive remains queryable after the 30-day Actions artifacts expire. [Archive workflow](../../../.github/workflows/BenchmarkHistory.yml)

```text
main/<commit-sha>/<actions-run-id>-<attempt>/record.json
main/<commit-sha>/<actions-run-id>-<attempt>/snapshot.json
main/<commit-sha>/<actions-run-id>-<attempt>/baseline.json       # paired attempts
pull_request/<commit-sha>/<actions-run-id>-<attempt>/record.json
pull_request/<commit-sha>/<actions-run-id>-<attempt>/snapshot.json
pull_request/<commit-sha>/<actions-run-id>-<attempt>/baseline.json
```

The build, test and measurement jobs use read-only repository permissions. The publisher runs the default branch's archive script with permission to write the history branch. It accepts bounded JSON files under validated commit paths. Both workflows must be installed on the default branch, and repository policies must permit the Actions token to write `benchmark-history`. [GitHub workflow completion events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run)

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

For the two-commit build handoff, Jev selected a foreign key on source commit and native profile. Z3 verified matching, unique producers and rejected a missing or duplicate matching release. Jev compiled the archive-key constraint with `data_integrity.unique`. Z3 accepted the commit/run/attempt key and found a collision when the attempt was removed. The workflow also runs integration tests against temporary Git remotes for multi-commit updates, concurrent writers, retries, rejected overwrites, and baseline selection.

```sh
python3 -B -m unittest discover -s benchmarks/provider_comparison/tracker -p 'test_*.py'
```

### Application Hybrid Query workloads

Use `tracker.py run --hybrid --case directory_join_topk` with the pinned host,
extension and `mod32` input. Omit `--case` to run the application suite. The
runner checks exact ordered Arrow results on both providers, replays the same
SQL in the pinned SQLLogic runner, and verifies the workload and observed call
order before writing the snapshot. The airport SQLLogic witness covers the
public route-directory query. The scaled case uses the matched creator graph as
a route/destination projection and joins it to a generated, hashed Parquet file.

`prepared_watchlist_churn` reuses one DuckDB prepared join across 63, 64 and
65 distinct keys. Each sample includes replacing the watchlist and fetching
each epoch. Untimed `scan_diagnostics.steps` records rows, offers and the applied
route per epoch. The top-level scan count is the sum across the three executions.
