# Bound graph planning on the SF1 creator projection

The two releases use the same DuckDB 2.0.1 library, SQL statements, five-key watchlist, and checkpointed provider files. The graph contains 3,809,607 creator edges. The CSV oracle sorts and hashes result rows while retaining duplicates. The baseline artifact has the SHA-256 recorded by the optimized benchmark at `f45c2c1` (`933742d94b9f…`). The candidate is the production build at `1ef6b47` (`a4cb4aa8b23d…`). Both runs used the same driver checkout. [Historical baseline observations](../optimized/mod1.json)

The fixture-backed SQLLogic case first ran against the archived release. A predicate through a view returned correct results, but the graph scan delivered all five Ladybug routes and all three RelateDB routes to DuckDB. The candidate delivered one route from each provider and passed all 19 assertions, including the NULL residual and explicit batch-limit errors. Jev 1.14.0 selected `data_integrity.cardinality` in both checks. Its completeness gate scored 0.39 before and 0.48 after, below the 0.60 threshold. Direct Z3 verification of the two one-row requirements failed for the measured baseline (`sol_32505f7ae0f34c72`) and passed for the measured candidate (`sol_ca7bfd55763641d3`). [SQLLogic case](../../../test/relate/planning_acceptance.test)

## Full-scale results

Both releases completed the six existing benchmark queries on both providers. Each candidate result matched the sorted CSV signature. The physical graph scans returned 6,465 rows for the source equality and 23,316 rows for the table watchlist. The scalar aggregate returned one row containing the edge count of 3,809,607 and checksum of 1,913,706,483,318. [Baseline benchmark](baseline.json) · [Candidate benchmark](candidate.json)

The alternating control adds a filter above a graph table and the same filter above a view. Both candidate plans returned 6,465 provider rows for these forms on both engines. The baseline Ladybug scan returned all 3,809,607 graph rows. Baseline RelateDB returned `QW_EXECUTION` for both forms on both attempts. Both releases also returned that error for a single-query export of all pairs on RelateDB, so the verification worker compared all pairs in 13 disjoint author ranges. The two-block order was baseline/candidate in block one and candidate/baseline in block two. Each successful case has six timed observations per release and provider, after a warmup. Each timed query executes and fetches all rows. P95 is nearest-rank and equals the slowest observation for these sample sizes. [Interleaved timings, errors and scan counts](paired.json)

| Workload | Provider | Baseline p50 ms | Candidate p50 ms | Baseline p95 ms | Candidate p95 ms |
|---|---|---:|---:|---:|---:|
| Standalone GQL lookup | ladybug | 4.04 | 4.08 | 7.41 | 6.78 |
| Standalone GQL lookup | relate | 2.43 | 2.46 | 2.79 | 2.71 |
| Standalone GQL fanout | ladybug | 7.01 | 8.20 | 10.08 | 12.11 |
| Standalone GQL fanout | relate | 7.68 | 7.30 | 7.76 | 7.99 |
| Standalone Cypher fanout | ladybug | 4.14 | 4.37 | 6.56 | 6.67 |
| Standalone Cypher fanout | relate | 5.37 | 5.27 | 5.51 | 6.52 |
| Graph-local equality | ladybug | 4.61 | 5.50 | 7.78 | 7.61 |
| Graph-local equality | relate | 6.18 | 6.21 | 6.53 | 7.23 |
| Table watchlist | ladybug | 11.07 | 12.94 | 18.05 | 17.76 |
| Table watchlist | relate | 45.51 | 44.80 | 47.52 | 50.17 |
| Full SQL scalar aggregate | ladybug | 125.96 | 139.39 | 177.92 | 184.71 |
| Full SQL scalar aggregate | relate | 2,523.02 | 2,496.46 | 2,964.15 | 2,555.18 |
| Outer SQL equality | ladybug | 391.37 | 5.22 | 560.19 | 7.35 |
| Outer SQL equality | relate | failed | 6.15 | failed | 7.12 |
| Equality through a view | ladybug | 401.44 | 5.63 | 578.28 | 8.07 |
| Equality through a view | relate | failed | 6.29 | failed | 7.19 |

Ladybug’s outer-predicate latency fell about 75× and the view latency about 71×. For the six established workloads, its mixed-control candidate medians were 1–19% higher, and the separate sequential runs favored the candidate for all six. The four-block control below runs each established Ladybug workload in a fresh process for each release, with alternating release order and 16 timed observations per workload and release. In isolation the scalar aggregate still took 3.5% longer at p50 and 14.1% longer at p95. Three of four blocks had a slower median. The other five isolated medians ranged from 5.8% faster to 0.5% slower. RelateDB's mixed-control medians for the established workloads varied by less than 5% between releases. [Isolated Ladybug timings](ladybug-isolated.json)

| Isolated Ladybug workload | Baseline p50 ms | Candidate p50 ms | Baseline p95 ms | Candidate p95 ms |
|---|---:|---:|---:|---:|
| Standalone GQL lookup | 2.39 | 2.34 | 4.77 | 2.64 |
| Standalone GQL fanout | 4.87 | 4.87 | 6.32 | 5.40 |
| Standalone Cypher fanout | 2.64 | 2.49 | 3.08 | 2.77 |
| Graph-local equality | 3.13 | 3.05 | 3.66 | 3.31 |
| Table watchlist | 8.15 | 8.19 | 9.86 | 9.59 |
| Full SQL scalar aggregate | 116.68 | 120.75 | 125.06 | 142.68 |

The following startup and peak-memory measurements come from the original driver. Each median covers two fresh processes per provider. The alternating control runs the outer-predicate plans before timing, so its process memory and first lookup are unsuitable for startup comparison.

| Provider | Release | Registration p50 ms | First lookup p50 ms | Max timed-worker RSS MiB |
|---|---|---:|---:|---:|
| ladybug | Baseline | 100.99 | 31.76 | 491 |
| ladybug | Candidate | 57.86 | 21.70 | 489 |
| relate | Baseline | 13,184.66 | 15.60 | 3,678 |
| relate | Candidate | 7,528.37 | 9.79 | 3,674 |

## Reproduce

Prepare the modulus-1 fixture and combined production release using the [provider comparison instructions](../README.md). Retain a separate copy of the baseline production extension. From the repository root, run the same driver for each release, then run the alternating control. Run the commands consecutively with the build finished, so compiler load does not enter the timings.

```sh
py=build/usage-client-venv/bin/python
bench=benchmarks/provider_comparison
fixture=build/perf/provider-comparison/mod1
baseline=/path/to/baseline/quack_weave.duckdb_extension
candidate=build/native/release/extension/quack_weave/quack_weave.duckdb_extension
out=build/perf/planning

"$py" -B "$bench/run.py" --fixture "$fixture" --extension "$baseline" \
  --blocks 2 --runs 3 --out "$out/baseline.json"
"$py" -B "$bench/run.py" --fixture "$fixture" --extension "$candidate" \
  --blocks 2 --runs 3 --out "$out/candidate.json"
"$py" -B "$bench/planning/compare.py" --fixture "$fixture" --baseline "$baseline" \
  --candidate "$candidate" --blocks 2 --runs 3 --out "$out/paired.json"
"$py" -B "$bench/paired.py" --isolated --fixture "$fixture" --baseline "$baseline" \
  --optimized "$candidate" --out "$out/ladybug-isolated.json"
```

The original driver checks source hashes before and after each run, validates the complete edge multiset in separate workers, records the first lookup after registration, and then times warm queries in seeded random order. Both releases run on each provider in a separate process with a fresh DuckDB instance. Registration includes opening a frozen graph. Operating-system file caches remain enabled. Peak RSS includes the whole process, the loaded extension, the graph engine and Arrow results. The alternating control adds an outer SQL equality and the same predicate through a view. It checks graph scan rows with `EXPLAIN (ANALYZE, FORMAT JSON)` and checks every successful timed result against the same reference. [Fixture-backed integration test](../../../test/relate/planning_acceptance.test)
