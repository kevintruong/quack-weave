# Ladybug vs RelateDB through QuackWeave

The [notebook](provider_benchmark.ipynb) compares the same DuckDB SQL through the two providers. Its DuckDB cells read the adjacent `mod*.json` files, which contain every timed observation, statement, fixture hash, result checksum, and measured graph-scan row count.

## Measured results on the full creator projection

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

Peak timed-worker RSS was 701 MiB for Ladybug and 4,064 MiB for RelateDB. Median registration was 77 ms and 8.49 s respectively. A warm DuckDB connection reuses Ladybug’s read-only handle, while the current Relate adapter opens a read-only handle for each scan. The measured latencies include each provider’s handle and result-conversion costs.

## Workload and measurement

The source is the [pinned Ladybug LSQB SF1 graph](../lsqb_sf1/watchlist.py). Each fixture retains only `Person.PersonId`, `Message.MessageId`, and `Message_hasCreator_Person`, including the endpoint people. Both files are built from the same sorted CSV. Ladybug uses primary keys on both IDs. RelateDB has a range index on each. Modulus 1 includes every creator edge in SF1. Moduli 32 and 256 select messages whose ID is divisible by that number.

The driver loads the same combined macOS arm64 extension into DuckDB 2.0.1 via ADBC, registers one provider with automatic catalog discovery, and sets DuckDB to one thread. The providers retain their internal defaults. Each workload executes and fetches all rows into Arrow. Result verification and dialect switches occur outside the timed interval. Every successful repetition must reproduce its CSV-derived answer. Separate verification workers compare the complete edge multiset and record the actual graph-scan cardinalities from `EXPLAIN ANALYZE`.

Each block uses one fresh process and connection per provider. The order alternates across blocks. After the first point lookup, each workload runs once to warm up and then runs in a shuffled order. OS caches remain enabled. First lookup and registration are reported separately. Worker peak RSS includes the whole timed process. The two smaller scales have 16 warm observations per query and provider. The full scale has six for each successful query. P95 uses nearest rank.

## Reproduce

From the repository root, use the benchmark Python environment with `ladybug==0.22.3`, `pyarrow`, `numpy`, and `adbc-driver-manager`. Place the pinned `sf1.lbdb` under `build/perf/lsqb-sf1/`. The fixture builder checks the source hash before importing. These commands target the combined release and the pinned DuckDB library used in the measurements.

```sh
make mvp2-deps mvp2-relate-release
cargo build --locked -p rusty_quack --target aarch64-apple-darwin --release \
  --features relate-provider --target-dir target/mvp2-relate --example relate_bench_load

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

Fixture creation requires a fresh destination. An existing fixture can be benchmarked again directly. To refresh the notebook with a new run, put its result files alongside the notebook as `mod256.json`, `mod32.json`, and `mod1.json`.

The following independent probe prints the native RelateDB error for the full unfiltered traversal. It uses a frozen read-only handle and bypasses QuackWeave only to expose the diagnostic. The benchmark timings all use QuackWeave.

```sh
target/mvp2-relate/aarch64-apple-darwin/release/examples/relate_bench_load \
  --probe build/perf/provider-comparison/mod1/social.rl \
  'MATCH (m:Message)-[:Message_hasCreator_Person]->(p:Person) RETURN p.PersonId AS author, m.MessageId AS mid'
```

On the measured release the probe returned `Capacity { used: 268435496, limit: 268435456, kind: Expression }`. The full-projection verification therefore counts every edge and compares disjoint author-range reads against the corresponding sorted CSV rows. Failed unpartitioned workloads keep their error status and have zero timing samples. The partitioned checks are outside every measured interval.
