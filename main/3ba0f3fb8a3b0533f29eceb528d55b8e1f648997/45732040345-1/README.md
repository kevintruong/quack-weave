### Benchmark `3ba0f3fb8a3b` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `7bdfb95c9518` on the same runner. The two releases alternated order across measurement blocks.

Latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**5 workloads with regressions · 14 with faster timings**

- ladybug/direct_cypher/lookup_miss (p50 +11.8%, p95 +30.9%)
- ladybug/qw_cypher/lookup (p95 +12.1%)
- ladybug/qw_gql/lookup (p95 +11.0%)
- relate/direct_cypher/lookup (p95 +17.5%)
- relate/direct_cypher/lookup_miss (p50 +11.4%)

#### Standalone graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.405 | 4.557 | — | 4.350 | +1.3% acceptable | 4.457 | +2.2% acceptable |
| ladybug | direct_cypher | lookup | 20 | 1.099 | 1.210 | — | 1.062 | +3.5% acceptable | 1.140 | +6.1% acceptable |
| ladybug | direct_cypher | lookup_miss | 20 | 0.410 | 0.547 | — | 0.367 | **+11.8% regression** | 0.418 | **+30.9% regression** |
| ladybug | qw_cypher | fanout | 20 | 5.556 | 5.751 | 1.26× | 5.445 | +2.0% acceptable | 5.680 | +1.2% acceptable |
| ladybug | qw_cypher | lookup | 20 | 1.993 | 2.347 | 1.81× | 1.912 | +4.3% acceptable | 2.093 | **+12.1% regression** |
| ladybug | qw_cypher | lookup_miss | 20 | 1.980 | 2.330 | 4.82× | 1.889 | +4.9% acceptable | 2.211 | +5.4% acceptable |
| ladybug | qw_gql | fanout | 20 | 5.843 | 6.122 | 1.33× | 5.760 | +1.4% acceptable | 5.989 | +2.2% acceptable |
| ladybug | qw_gql | lookup | 20 | 2.196 | 2.689 | 2.00× | 2.093 | +4.9% acceptable | 2.422 | **+11.0% regression** |
| ladybug | qw_gql | lookup_miss | 20 | 2.210 | 2.624 | 5.38× | 2.089 | +5.7% acceptable | 2.434 | +7.8% acceptable |
| relate | direct_cypher | fanout | 20 | 11.011 | 11.227 | — | 10.915 | +0.9% acceptable | 11.089 | +1.2% acceptable |
| relate | direct_cypher | lookup | 20 | 0.191 | 0.360 | — | 0.180 | +6.4% acceptable | 0.306 | **+17.5% regression** |
| relate | direct_cypher | lookup_miss | 20 | 0.338 | 0.438 | — | 0.304 | **+11.4% regression** | 0.416 | +5.3% acceptable |
| relate | qw_cypher | fanout | 20 | 11.356 | 11.729 | 1.03× | 11.513 | **-1.4% faster** | 11.774 | **-0.4% faster** |
| relate | qw_cypher | lookup | 20 | 2.147 | 2.649 | 11.23× | 2.108 | +1.8% acceptable | 2.695 | **-1.7% faster** |
| relate | qw_cypher | lookup_miss | 20 | 2.301 | 2.700 | 6.80× | 2.121 | +8.5% acceptable | 2.594 | +4.1% acceptable |
| relate | qw_gql | fanout | 20 | 11.484 | 11.777 | 1.04× | 11.649 | **-1.4% faster** | 11.914 | **-1.2% faster** |
| relate | qw_gql | lookup | 20 | 2.233 | 2.817 | 11.68× | 2.259 | **-1.1% faster** | 2.834 | **-0.6% faster** |
| relate | qw_gql | lookup_miss | 20 | 2.427 | 2.846 | 7.17× | 2.336 | +3.9% acceptable | 3.021 | **-5.8% faster** |

#### Hybrid SQL and graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 292.063 | 299.827 | — | 285.120 | +2.4% acceptable | 292.084 | +2.7% acceptable |
| ladybug | qw_pgq | graph_table_where | 20 | 7.027 | 7.219 | — | 6.856 | +2.5% acceptable | 7.053 | +2.4% acceptable |
| ladybug | qw_pgq | outer_where | 20 | 6.952 | 7.190 | — | 6.879 | +1.1% acceptable | 7.129 | +0.9% acceptable |
| ladybug | qw_pgq | table_watchlist | 20 | 14.940 | 15.700 | — | 14.924 | +0.1% acceptable | 15.858 | **-1.0% faster** |
| ladybug | qw_pgq | values_watchlist | 20 | 14.375 | 14.968 | — | 14.283 | +0.6% acceptable | 15.326 | **-2.3% faster** |
| ladybug | qw_pgq | view_where | 20 | 7.853 | 8.062 | — | 7.736 | +1.5% acceptable | 8.064 | **>-0.1% faster** |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,894.278 | 4,921.707 | — | 4,921.510 | **-0.6% faster** | 4,975.218 | **-1.1% faster** |
| relate | qw_pgq | graph_table_where | 20 | 13.515 | 13.813 | — | 13.672 | **-1.2% faster** | 13.869 | **-0.4% faster** |
| relate | qw_pgq | outer_where | 20 | 13.483 | 13.684 | — | 13.544 | **-0.4% faster** | 13.939 | **-1.8% faster** |
| relate | qw_pgq | table_watchlist | 20 | 91.374 | 93.183 | — | 91.783 | **-0.4% faster** | 92.988 | +0.2% acceptable |
| relate | qw_pgq | values_watchlist | 20 | 90.037 | 92.014 | — | 90.668 | **-0.7% faster** | 91.954 | +0.1% acceptable |
| relate | qw_pgq | view_where | 20 | 14.261 | 14.614 | — | 14.337 | **-0.5% faster** | 14.893 | **-1.9% faster** |

