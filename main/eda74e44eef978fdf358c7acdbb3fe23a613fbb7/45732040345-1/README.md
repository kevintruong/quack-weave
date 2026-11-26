### Benchmark `eda74e44eef9` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `7bdfb95c9518` on the same runner. The two releases alternated order across measurement blocks.

Latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**4 workloads with regressions · 26 with faster timings**

- relate/direct_cypher/lookup_miss (p50 +11.8%, p95 +11.1%)
- relate/qw_cypher/fanout (p95 +57.0%)
- relate/qw_cypher/lookup_miss (p95 +402.8%)
- relate/qw_gql/fanout (p95 +34.3%)

#### Standalone graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.303 | 4.394 | — | 4.301 | +0.1% acceptable | 4.333 | +1.4% acceptable |
| ladybug | direct_cypher | lookup | 20 | 1.037 | 1.072 | — | 1.041 | **-0.3% faster** | 1.057 | +1.4% acceptable |
| ladybug | direct_cypher | lookup_miss | 20 | 0.323 | 0.376 | — | 0.343 | **-5.7% faster** | 0.390 | **-3.6% faster** |
| ladybug | qw_cypher | fanout | 20 | 5.276 | 5.362 | 1.23× | 5.386 | **-2.0% faster** | 6.555 | **-18.2% faster** |
| ladybug | qw_cypher | lookup | 20 | 1.705 | 1.790 | 1.64× | 1.801 | **-5.3% faster** | 2.906 | **-38.4% faster** |
| ladybug | qw_cypher | lookup_miss | 20 | 1.685 | 1.769 | 5.22× | 1.790 | **-5.9% faster** | 3.178 | **-44.3% faster** |
| ladybug | qw_gql | fanout | 20 | 5.577 | 5.716 | 1.30× | 5.618 | **-0.7% faster** | 5.739 | **-0.4% faster** |
| ladybug | qw_gql | lookup | 20 | 1.933 | 2.030 | 1.86× | 2.007 | **-3.7% faster** | 2.147 | **-5.4% faster** |
| ladybug | qw_gql | lookup_miss | 20 | 1.909 | 1.974 | 5.91× | 1.952 | **-2.2% faster** | 2.074 | **-4.8% faster** |
| relate | direct_cypher | fanout | 20 | 10.820 | 11.013 | — | 10.766 | +0.5% acceptable | 11.046 | **-0.3% faster** |
| relate | direct_cypher | lookup | 20 | 0.177 | 0.252 | — | 0.173 | +2.8% acceptable | 0.271 | **-7.0% faster** |
| relate | direct_cypher | lookup_miss | 20 | 0.284 | 0.403 | — | 0.254 | **+11.8% regression** | 0.362 | **+11.1% regression** |
| relate | qw_cypher | fanout | 20 | 11.172 | 18.048 | 1.03× | 11.305 | **-1.2% faster** | 11.496 | **+57.0% regression** |
| relate | qw_cypher | lookup | 20 | 1.860 | 2.148 | 10.49× | 1.884 | **-1.3% faster** | 2.184 | **-1.6% faster** |
| relate | qw_cypher | lookup_miss | 20 | 1.892 | 10.812 | 6.66× | 1.871 | +1.1% acceptable | 2.150 | **+402.8% regression** |
| relate | qw_gql | fanout | 20 | 11.386 | 15.644 | 1.05× | 11.466 | **-0.7% faster** | 11.648 | **+34.3% regression** |
| relate | qw_gql | lookup | 20 | 2.012 | 2.266 | 11.35× | 2.041 | **-1.4% faster** | 2.326 | **-2.6% faster** |
| relate | qw_gql | lookup_miss | 20 | 1.988 | 2.280 | 7.00× | 2.074 | **-4.2% faster** | 2.221 | +2.7% acceptable |

#### Hybrid SQL and graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 273.795 | 278.570 | — | 270.067 | +1.4% acceptable | 280.001 | **-0.5% faster** |
| ladybug | qw_pgq | graph_table_where | 20 | 6.324 | 6.893 | — | 6.328 | **-0.1% faster** | 6.983 | **-1.3% faster** |
| ladybug | qw_pgq | outer_where | 20 | 6.335 | 6.936 | — | 6.386 | **-0.8% faster** | 7.033 | **-1.4% faster** |
| ladybug | qw_pgq | table_watchlist | 20 | 14.080 | 15.440 | — | 14.417 | **-2.3% faster** | 15.247 | +1.3% acceptable |
| ladybug | qw_pgq | values_watchlist | 20 | 13.622 | 14.334 | — | 13.697 | **-0.5% faster** | 15.237 | **-5.9% faster** |
| ladybug | qw_pgq | view_where | 20 | 7.081 | 7.701 | — | 7.375 | **-4.0% faster** | 7.785 | **-1.1% faster** |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,902.621 | 4,935.197 | — | 4,917.753 | **-0.3% faster** | 4,964.973 | **-0.6% faster** |
| relate | qw_pgq | graph_table_where | 20 | 13.238 | 13.744 | — | 13.373 | **-1.0% faster** | 13.666 | +0.6% acceptable |
| relate | qw_pgq | outer_where | 20 | 13.259 | 13.413 | — | 13.405 | **-1.1% faster** | 13.588 | **-1.3% faster** |
| relate | qw_pgq | table_watchlist | 20 | 91.043 | 92.345 | — | 91.275 | **-0.3% faster** | 93.761 | **-1.5% faster** |
| relate | qw_pgq | values_watchlist | 20 | 89.548 | 90.518 | — | 89.471 | +0.1% acceptable | 90.510 | <+0.1% acceptable |
| relate | qw_pgq | view_where | 20 | 13.844 | 14.163 | — | 14.233 | **-2.7% faster** | 14.548 | **-2.6% faster** |

