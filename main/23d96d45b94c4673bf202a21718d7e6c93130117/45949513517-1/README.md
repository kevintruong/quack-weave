### Benchmark `23d96d45b94c` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `54b2db6047ca` on the same runner. The two releases alternated order across measurement blocks.

Warm client latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**1 workloads with regressions · 14 with faster timings**

- relate/direct_cypher/lookup (p95 +16.9%)

#### Standalone graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.261 | 4.329 | — | 4.281 | **-0.5% faster** | 4.373 | **-1.0% faster** |
| ladybug | direct_cypher | lookup | 20 | 1.008 | 1.035 | — | 1.014 | **-0.6% faster** | 1.035 | <+0.1% acceptable |
| ladybug | direct_cypher | lookup_miss | 20 | 0.306 | 0.350 | — | 0.320 | **-4.2% faster** | 0.347 | +0.9% acceptable |
| ladybug | qw_cypher | fanout | 20 | 5.165 | 5.256 | 1.21× | 5.174 | **-0.2% faster** | 5.233 | +0.4% acceptable |
| ladybug | qw_cypher | lookup | 20 | 1.645 | 1.820 | 1.63× | 1.655 | **-0.6% faster** | 1.688 | +7.8% acceptable |
| ladybug | qw_cypher | lookup_miss | 20 | 1.597 | 1.741 | 5.22× | 1.601 | **-0.2% faster** | 1.668 | +4.4% acceptable |
| ladybug | qw_gql | fanout | 20 | 5.419 | 5.590 | 1.27× | 5.415 | +0.1% acceptable | 5.558 | +0.6% acceptable |
| ladybug | qw_gql | lookup | 20 | 1.837 | 1.967 | 1.82× | 1.822 | +0.8% acceptable | 1.885 | +4.3% acceptable |
| ladybug | qw_gql | lookup_miss | 20 | 1.800 | 1.932 | 5.88× | 1.781 | +1.0% acceptable | 1.878 | +2.9% acceptable |
| relate | direct_cypher | fanout | 20 | 10.640 | 10.832 | — | 10.692 | **-0.5% faster** | 10.866 | **-0.3% faster** |
| relate | direct_cypher | lookup | 20 | 0.156 | 0.240 | — | 0.169 | **-7.5% faster** | 0.205 | **+16.9% regression** |
| relate | direct_cypher | lookup_miss | 20 | 0.229 | 0.325 | — | 0.226 | +1.3% acceptable | 0.318 | +2.2% acceptable |
| relate | qw_cypher | fanout | 20 | 10.916 | 11.154 | 1.03× | 10.934 | **-0.2% faster** | 11.304 | **-1.3% faster** |
| relate | qw_cypher | lookup | 20 | 1.621 | 1.808 | 10.38× | 1.667 | **-2.7% faster** | 1.870 | **-3.3% faster** |
| relate | qw_cypher | lookup_miss | 20 | 1.647 | 1.772 | 7.18× | 1.666 | **-1.2% faster** | 1.824 | **-2.9% faster** |
| relate | qw_gql | fanout | 20 | 11.224 | 11.508 | 1.05× | 11.132 | +0.8% acceptable | 11.347 | +1.4% acceptable |
| relate | qw_gql | lookup | 20 | 1.831 | 2.011 | 11.72× | 1.839 | **-0.5% faster** | 2.146 | **-6.3% faster** |
| relate | qw_gql | lookup_miss | 20 | 1.831 | 2.127 | 7.99× | 1.855 | **-1.3% faster** | 2.054 | +3.6% acceptable |

#### Hybrid SQL and graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 251.822 | 282.673 | — | 251.641 | +0.1% acceptable | 261.789 | +8.0% acceptable |
| ladybug | qw_pgq | graph_table_where | 20 | 6.165 | 6.894 | — | 5.939 | +3.8% acceptable | 6.699 | +2.9% acceptable |
| ladybug | qw_pgq | outer_where | 20 | 5.989 | 6.884 | — | 5.973 | +0.3% acceptable | 6.626 | +3.9% acceptable |
| ladybug | qw_pgq | table_watchlist | 20 | 13.760 | 14.406 | — | 13.605 | +1.1% acceptable | 14.220 | +1.3% acceptable |
| ladybug | qw_pgq | values_watchlist | 20 | 12.887 | 14.021 | — | 13.034 | **-1.1% faster** | 14.003 | +0.1% acceptable |
| ladybug | qw_pgq | view_where | 20 | 6.979 | 7.460 | — | 6.636 | +5.2% acceptable | 7.387 | +1.0% acceptable |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,987.895 | 5,051.684 | — | 4,924.723 | +1.3% acceptable | 4,991.500 | +1.2% acceptable |
| relate | qw_pgq | graph_table_where | 20 | 13.119 | 13.432 | — | 13.076 | +0.3% acceptable | 13.394 | +0.3% acceptable |
| relate | qw_pgq | outer_where | 20 | 13.128 | 13.537 | — | 13.069 | +0.5% acceptable | 13.258 | +2.1% acceptable |
| relate | qw_pgq | table_watchlist | 20 | 90.769 | 92.403 | — | 90.315 | +0.5% acceptable | 91.371 | +1.1% acceptable |
| relate | qw_pgq | values_watchlist | 20 | 89.638 | 91.361 | — | 88.917 | +0.8% acceptable | 90.675 | +0.8% acceptable |
| relate | qw_pgq | view_where | 20 | 13.892 | 14.373 | — | 13.639 | +1.8% acceptable | 13.979 | +2.8% acceptable |

