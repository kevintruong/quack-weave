# Ladybug vs RelateDB through QuackWeave

The notebook compares the same DuckDB SQL through the two providers. Its DuckDB cells read baseline and optimized observations, including SQL, fixture hashes, result checksums and measured graph-scan row counts. [Executed comparison notebook](provider_benchmark.ipynb)

The benchmark tracker also measures direct Ladybug and direct RelateDB for standalone graph queries. It tracks hybrid SQL workloads through QuackWeave on both providers, with immutable snapshots and a DuckDB history query. [Standalone baselines and hybrid tracker](tracker/README.md)

## Optimized release on the full SF1 creator graph

All six queries completed on both providers using the same pinned DuckDB build, graph files, SQL and CSV-derived expected results as the baseline. The table shows median warm, end-to-end fetch latency over six observations per successful query. Timing includes DuckDB binding and graph-to-Arrow conversion. [Optimized full-scale observations](optimized/mod1.json) · [Baseline observations](mod1.json)

| Workload | Ladybug before | Ladybug after | RelateDB before | RelateDB after |
|---|---:|---:|---:|---:|
| Bare GQL author lookup | 2.81 ms | 6.07 ms | 6.94 s | 4.09 ms |
| Bare GQL author messages | 5.20 ms | 11.66 ms | 6.90 s | 12.69 ms |
| Bare Cypher author messages | 2.62 ms | 5.79 ms | 6.98 s | 8.82 ms |
| GRAPH_TABLE equality | 3.50 ms | 7.57 ms | failed | 10.24 ms |
| DuckDB table watchlist and grouping | 358.40 ms | 17.56 ms | failed | 76.94 ms |
| Full traversal with SQL count and sum | 96.60 ms | 180.34 ms | failed | 4.52 s |

Both providers returned 6,465 graph rows for the equality filter, 23,316 for the table watchlist, and one for the scalar aggregate. The aggregate counted 3,809,607 edges and returned an exact checksum of 1,913,706,483,318. The watchlist produced four groups.

RelateDB loads its frozen graph at registration and each scan creates an independent connection. Median registration took 13.74 s for RelateDB and 112.35 ms for Ladybug. Peak timed-worker RSS was 3,672 MiB and 491 MiB respectively. These costs matter when an application opens a fresh instance per request.

The unfiltered, two-column RelateDB export still reached its native 256 MiB expression allocation limit. The verification worker compared every edge against the CSV in disjoint author ranges. Each of the six timed workloads ran as one query. Smaller-scale raw observations include 16 warm runs per provider and workload. [Modulus 32](optimized/mod32.json) · [Modulus 256](optimized/mod256.json)

## Ladybug release controls

The neighboring runs compare the archived baseline extension and the new extension against the same SF1 file on the same host. Four blocks alternate release order. Each release contributes 16 warm observations per workload. Mixed runs shuffle the six queries on one connection. Isolated runs start a separate process and connection for each workload and release. All numbers below are median milliseconds. [Mixed observations](optimized/ladybug-paired.json) · [Isolated observations](optimized/ladybug-isolated.json)

| Workload | Mixed before | Mixed after | Isolated before | Isolated after |
|---|---:|---:|---:|---:|
| `gql_lookup` | 4.75 | 5.56 | 3.31 | 3.58 |
| `gql_fanout` | 9.25 | 11.05 | 9.08 | 10.37 |
| `cypher_fanout` | 4.53 | 5.75 | 6.38 | 5.05 |
| `graph_table_where` | 6.01 | 7.43 | 4.23 | 4.44 |
| `table_watchlist` | 593.48 | 16.65 | 597.92 | 11.74 |
| `full_scan_aggregate` | 142.60 | 172.73 | 170.34 | 186.45 |

The watchlist improved in all four blocks of both controls. In isolation it fell from 597.92 ms to 11.74 ms, about 51× faster. The two fanout dialects moved in different directions. Cypher improved 20.9% and GQL took 14.2% longer. The remaining isolated medians rose by 5.1% to 9.5%. The raw observations include block order and tails. A single machine and four blocks limit conclusions about small changes.

To reproduce, pass the packaged extension from baseline commit `1bf62f0` to the paired driver. Both extension files must target the same pinned DuckDB ABI.

```sh
build/usage-client-venv/bin/python -B benchmarks/provider_comparison/paired.py \
  --fixture build/perf/provider-comparison/mod1 --baseline /path/to/baseline/quack_weave.duckdb_extension \
  --out build/perf/provider-comparison/ladybug-paired.json

build/usage-client-venv/bin/python -B benchmarks/provider_comparison/paired.py --isolated \
  --fixture build/perf/provider-comparison/mod1 --baseline /path/to/baseline/quack_weave.duckdb_extension \
  --out build/perf/provider-comparison/ladybug-isolated.json
```

## Baseline on the full creator projection

Each file contains the same 3,809,607 messages and creator edges and 10,947 people. The selected author has 6,465 messages. Warm wall-clock medians include fetching the entire result. [Full observations](mod1.json)

| Query through QuackWeave | Ladybug 0.22.3 | RelateDB 1.2.0 |
|---|---:|---:|
| Bare GQL, one author by ID | 2.81 ms | 6.94 s |
| Bare GQL, one author’s messages | 5.20 ms | 6.90 s |
| Bare Cypher, one author’s messages | 2.62 ms | 6.98 s |
| `GRAPH_TABLE` equality filter | 3.50 ms | `QW_EXECUTION` |
| DuckDB watchlist table join and grouping | 358.40 ms | `QW_EXECUTION` |
| Full traversal with SQL count and sum | 96.60 ms | `QW_EXECUTION` |

The Ladybug equality filter delivered 6,465 graph rows to DuckDB. The table watchlist delivered all 3,809,607 before the DuckDB join reduced them to four groups. The aggregate delivered one graph row. RelateDB completed all six queries on the two smaller projections. The native two-column scan on the full projection reached the expression-memory limit described below.

Peak timed-worker RSS was 701 MiB for Ladybug and 4,064 MiB for RelateDB. Median registration was 77 ms and 8.49 s respectively. In the baseline, a warm DuckDB connection reused Ladybug’s read-only handle and the Relate adapter opened a read-only handle for each scan. The measured latencies include each provider’s handle and result-conversion costs.

## Workload and measurement

The source is the [pinned Ladybug LSQB SF1 graph](../lsqb_sf1/watchlist.py). Each fixture retains only `Person.PersonId`, `Message.MessageId`, and `Message_hasCreator_Person`, including the endpoint people. Both files are built from the same sorted CSV. Ladybug uses primary keys on both IDs. RelateDB has a range index on each. Modulus 1 includes every creator edge in SF1. Moduli 32 and 256 select messages whose ID is divisible by that number.

The driver loads the same combined macOS arm64 extension into DuckDB 2.0.1 via ADBC, registers one provider with automatic catalog discovery, and sets DuckDB to one thread. The providers retain their internal defaults. Each workload executes and fetches all rows into Arrow. Result verification and dialect switches occur outside the timed interval. Every successful repetition must reproduce its CSV-derived answer. Separate verification workers compare the complete edge multiset and record the actual graph-scan cardinalities from `EXPLAIN ANALYZE`.

Each block uses one fresh process and connection per provider. The order alternates across blocks. After the first point lookup, each workload runs once to warm up and then runs in a shuffled order. OS caches remain enabled. First lookup and registration are reported separately. Worker peak RSS includes the whole timed process. The two smaller scales have 16 warm observations per query and provider. The full scale has six for each successful query. P95 uses nearest rank.

## Regression and solver checks

Each implementation commit has a fixture-backed SQLLogic regression. The plan checks count the graph rows delivered to DuckDB. The paired Jev and Z3 checks below describe the modeled invariants. Wall-clock measurements come from the benchmark driver.

| Change | Baseline evidence | Optimized evidence |
|---|---|---|
| DuckDB table watchlist with `USING` | Extra graph rows, cardinality violation `sol_93a4088416d349e0` | Exact filtered cardinality `sol_52d427010b3e4f40` |
| RelateDB snapshot reuse | Three physical read opens for registration and two scans, capacity violation `sol_c4e13cac179e4a12` | One physical open `sol_ca3452a6a19143a4` |
| RelateDB predicates | Original Jev completeness gate blocked. Direct verification of three rows against a one-row requirement failed `sol_2926bcdc147c4b27` | Open Jev gate and exact cardinality `sol_0d1d9dc2d3bc46f1` |
| RelateDB scalar aggregate | Fixture checksum matched `sol_7612a491cc4d4262`, SQLLogic failed the one-row provider plan | Same checksum `sol_bdabed9d97e04ae8`, SQLLogic passed the one-row plan. Z3 verified the partial-sum bound `sol_052a19cf03d644c4` |
| Combined SF1 acceptance | Three of six RelateDB workloads completed `sol_88172e73bcbe4dd6` | Six of six completed `sol_eb522eb0b1484154` |

## Reproduce

From the repository root, use the benchmark Python environment with Python 3.12 and the [pinned benchmark wheels](tracker/requirements.txt). Place the pinned `sf1.lbdb` under `build/perf/lsqb-sf1/`. The fixture builder checks the source hash before importing. These commands target the combined release and the pinned DuckDB library used in the measurements.

```sh
make mvp2-deps mvp2-relate-release
build/usage-client-venv/bin/python -m pip install --only-binary=:all: --require-hashes -r benchmarks/provider_comparison/tracker/requirements.txt

for m in 256 32 1; do
  build/usage-client-venv/bin/python -B benchmarks/provider_comparison/prepare.py --modulus "$m"
done

for m in 256 32; do
  build/usage-client-venv/bin/python -B benchmarks/provider_comparison/run.py \
    --fixture "build/perf/provider-comparison/mod$m" \
    --out "build/perf/provider-comparison/results-mod$m.json"
done

build/usage-client-venv/bin/python -B benchmarks/provider_comparison/run.py \
  --fixture build/perf/provider-comparison/mod1 --runs 3 --blocks 2 \
  --out build/perf/provider-comparison/results-mod1.json
```

Fixture creation requires a fresh destination. An existing fixture can be benchmarked again directly. The notebook reads baseline files from its own directory and the new full-scale run from `optimized/mod1.json`. To update the comparison, point the benchmark’s `--out` at the corresponding file under `benchmarks/provider_comparison/optimized/`.

The following independent probe prints the native RelateDB error for the full unfiltered traversal. It uses a frozen read-only handle and bypasses QuackWeave only to expose the diagnostic. The benchmark timings all use QuackWeave.

```sh
cargo run --locked -p rusty_quack --release --features relate-provider --example relate_bench_load -- \
  --probe build/perf/provider-comparison/mod1/social.rl \
  'MATCH (m:Message)-[:Message_hasCreator_Person]->(p:Person) RETURN p.PersonId AS author, m.MessageId AS mid'
```

On the measured release the probe returned `Capacity { used: 268435496, limit: 268435456, kind: Expression }`. The full-projection verification therefore counts every edge and compares disjoint author-range reads against the corresponding sorted CSV rows. Failed unpartitioned workloads keep their error status and have zero timing samples. The partitioned checks are outside every measured interval.
