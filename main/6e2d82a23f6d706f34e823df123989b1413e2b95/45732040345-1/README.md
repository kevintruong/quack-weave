### Benchmark `6e2d82a23f6d` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `7bdfb95c9518` on the same runner. The two releases alternated order across measurement blocks.

Latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**1 workloads with regressions · 27 with faster timings**

- ladybug/direct_cypher/lookup_miss (p50 +10.7%)

#### Standalone graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.276 | 4.340 | — | 4.275 | <+0.1% acceptable | 4.358 | **-0.4% faster** |
| ladybug | direct_cypher | lookup | 20 | 1.038 | 1.082 | — | 1.015 | +2.2% acceptable | 1.051 | +3.0% acceptable |
| ladybug | direct_cypher | lookup_miss | 20 | 0.344 | 0.373 | — | 0.310 | **+10.7% regression** | 0.372 | +0.4% acceptable |
| ladybug | qw_cypher | fanout | 20 | 5.341 | 5.428 | 1.25× | 5.390 | **-0.9% faster** | 5.469 | **-0.7% faster** |
| ladybug | qw_cypher | lookup | 20 | 1.799 | 1.863 | 1.73× | 1.819 | **-1.1% faster** | 1.889 | **-1.4% faster** |
| ladybug | qw_cypher | lookup_miss | 20 | 1.764 | 1.819 | 5.13× | 1.822 | **-3.2% faster** | 1.933 | **-5.9% faster** |
| ladybug | qw_gql | fanout | 20 | 5.567 | 5.694 | 1.30× | 5.704 | **-2.4% faster** | 5.912 | **-3.7% faster** |
| ladybug | qw_gql | lookup | 20 | 1.974 | 2.065 | 1.90× | 2.070 | **-4.7% faster** | 2.186 | **-5.5% faster** |
| ladybug | qw_gql | lookup_miss | 20 | 1.945 | 2.013 | 5.66× | 2.047 | **-5.0% faster** | 2.134 | **-5.7% faster** |
| relate | direct_cypher | fanout | 20 | 10.791 | 10.998 | — | 10.789 | <+0.1% acceptable | 10.983 | +0.1% acceptable |
| relate | direct_cypher | lookup | 20 | 0.171 | 0.235 | — | 0.174 | **-2.0% faster** | 0.238 | **-1.2% faster** |
| relate | direct_cypher | lookup_miss | 20 | 0.242 | 0.323 | — | 0.256 | **-5.8% faster** | 0.362 | **-10.9% faster** |
| relate | qw_cypher | fanout | 20 | 11.088 | 11.497 | 1.03× | 11.437 | **-3.1% faster** | 11.824 | **-2.8% faster** |
| relate | qw_cypher | lookup | 20 | 1.728 | 2.025 | 10.13× | 1.966 | **-12.1% faster** | 2.511 | **-19.4% faster** |
| relate | qw_cypher | lookup_miss | 20 | 1.771 | 2.209 | 7.33× | 1.954 | **-9.4% faster** | 2.489 | **-11.2% faster** |
| relate | qw_gql | fanout | 20 | 11.341 | 11.555 | 1.05× | 11.644 | **-2.6% faster** | 11.876 | **-2.7% faster** |
| relate | qw_gql | lookup | 20 | 1.928 | 2.176 | 11.30× | 2.105 | **-8.4% faster** | 2.618 | **-16.9% faster** |
| relate | qw_gql | lookup_miss | 20 | 1.994 | 2.230 | 8.25× | 2.172 | **-8.2% faster** | 2.736 | **-18.5% faster** |

#### Hybrid SQL and graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 261.401 | 269.574 | — | 263.110 | **-0.6% faster** | 283.365 | **-4.9% faster** |
| ladybug | qw_pgq | graph_table_where | 20 | 6.145 | 6.906 | — | 6.248 | **-1.7% faster** | 7.088 | **-2.6% faster** |
| ladybug | qw_pgq | outer_where | 20 | 6.142 | 6.875 | — | 6.316 | **-2.8% faster** | 7.013 | **-2.0% faster** |
| ladybug | qw_pgq | table_watchlist | 20 | 14.014 | 14.707 | — | 14.224 | **-1.5% faster** | 15.386 | **-4.4% faster** |
| ladybug | qw_pgq | values_watchlist | 20 | 13.248 | 13.848 | — | 13.520 | **-2.0% faster** | 14.236 | **-2.7% faster** |
| ladybug | qw_pgq | view_where | 20 | 7.004 | 7.660 | — | 7.169 | **-2.3% faster** | 7.714 | **-0.7% faster** |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,897.681 | 4,981.447 | — | 4,908.891 | **-0.2% faster** | 4,951.818 | +0.6% acceptable |
| relate | qw_pgq | graph_table_where | 20 | 13.197 | 13.572 | — | 13.398 | **-1.5% faster** | 13.667 | **-0.7% faster** |
| relate | qw_pgq | outer_where | 20 | 13.247 | 13.547 | — | 13.482 | **-1.7% faster** | 13.776 | **-1.7% faster** |
| relate | qw_pgq | table_watchlist | 20 | 90.495 | 91.512 | — | 90.680 | **-0.2% faster** | 92.270 | **-0.8% faster** |
| relate | qw_pgq | values_watchlist | 20 | 89.265 | 90.934 | — | 89.391 | **-0.1% faster** | 91.123 | **-0.2% faster** |
| relate | qw_pgq | view_where | 20 | 13.958 | 14.382 | — | 14.250 | **-2.1% faster** | 14.458 | **-0.5% faster** |

