### Benchmark `3e28489e33e6` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `4e20651be8a1` on the same runner. The two releases alternated order across measurement blocks.

Warm client latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**4 workloads with regressions · 14 with faster timings**

- ladybug/direct_cypher/lookup_miss (p95 +12.7%)
- ladybug/qw_cypher/lookup (p95 +10.7%)
- ladybug/qw_gql/lookup (p95 +10.1%)
- relate/qw_pgq/graph_table_where (p95 +18.0%)

#### Standalone graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.371 | 4.458 | — | 4.376 | **-0.1% faster** | 4.464 | **-0.1% faster** |
| ladybug | direct_cypher | lookup | 20 | 1.051 | 1.128 | — | 1.053 | **-0.2% faster** | 1.105 | +2.1% acceptable |
| ladybug | direct_cypher | lookup_miss | 20 | 0.344 | 0.426 | — | 0.349 | **-1.5% faster** | 0.378 | **+12.7% regression** |
| ladybug | qw_cypher | fanout | 20 | 5.502 | 5.686 | 1.26× | 5.426 | +1.4% acceptable | 5.520 | +3.0% acceptable |
| ladybug | qw_cypher | lookup | 20 | 1.898 | 2.092 | 1.81× | 1.839 | +3.2% acceptable | 1.890 | **+10.7% regression** |
| ladybug | qw_cypher | lookup_miss | 20 | 1.872 | 2.035 | 5.44× | 1.802 | +3.9% acceptable | 1.902 | +7.0% acceptable |
| ladybug | qw_gql | fanout | 20 | 5.727 | 5.989 | 1.31× | 5.771 | **-0.8% faster** | 6.029 | **-0.7% faster** |
| ladybug | qw_gql | lookup | 20 | 2.122 | 2.441 | 2.02× | 2.081 | +2.0% acceptable | 2.217 | **+10.1% regression** |
| ladybug | qw_gql | lookup_miss | 20 | 2.089 | 2.389 | 6.07× | 2.062 | +1.4% acceptable | 2.209 | +8.2% acceptable |
| relate | direct_cypher | fanout | 20 | 10.795 | 10.930 | — | 10.830 | **-0.3% faster** | 11.781 | **-7.2% faster** |
| relate | direct_cypher | lookup | 20 | 0.171 | 0.285 | — | 0.186 | **-7.9% faster** | 0.269 | +5.9% acceptable |
| relate | direct_cypher | lookup_miss | 20 | 0.265 | 0.378 | — | 0.287 | **-7.7% faster** | 0.498 | **-24.0% faster** |
| relate | qw_cypher | fanout | 20 | 11.388 | 11.555 | 1.05× | 11.307 | +0.7% acceptable | 11.604 | **-0.4% faster** |
| relate | qw_cypher | lookup | 20 | 2.087 | 2.352 | 12.21× | 1.904 | +9.7% acceptable | 2.317 | +1.5% acceptable |
| relate | qw_cypher | lookup_miss | 20 | 1.986 | 2.403 | 7.51× | 1.894 | +4.8% acceptable | 2.292 | +4.8% acceptable |
| relate | qw_gql | fanout | 20 | 11.644 | 12.027 | 1.08× | 11.667 | **-0.2% faster** | 12.152 | **-1.0% faster** |
| relate | qw_gql | lookup | 20 | 2.251 | 2.668 | 13.17× | 2.256 | **-0.2% faster** | 23.676 | **-88.7% faster** |
| relate | qw_gql | lookup_miss | 20 | 2.215 | 2.948 | 8.37× | 2.234 | **-0.8% faster** | 2.828 | +4.2% acceptable |

#### Hybrid SQL and graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 303.561 | 310.871 | — | 298.290 | +1.8% acceptable | 305.054 | +1.9% acceptable |
| ladybug | qw_pgq | graph_table_where | 20 | 6.689 | 7.339 | — | 6.569 | +1.8% acceptable | 7.108 | +3.2% acceptable |
| ladybug | qw_pgq | outer_where | 20 | 6.773 | 7.120 | — | 6.609 | +2.5% acceptable | 7.142 | **-0.3% faster** |
| ladybug | qw_pgq | table_watchlist | 20 | 14.942 | 15.859 | — | 14.770 | +1.2% acceptable | 15.353 | +3.3% acceptable |
| ladybug | qw_pgq | values_watchlist | 20 | 13.855 | 15.074 | — | 13.914 | **-0.4% faster** | 15.065 | +0.1% acceptable |
| ladybug | qw_pgq | view_where | 20 | 7.668 | 8.192 | — | 7.401 | +3.6% acceptable | 7.984 | +2.6% acceptable |
| relate | qw_pgq | full_scan_aggregate | 20 | 5,003.678 | 5,074.329 | — | 4,947.403 | +1.1% acceptable | 5,002.403 | +1.4% acceptable |
| relate | qw_pgq | graph_table_where | 20 | 13.759 | 16.300 | — | 13.571 | +1.4% acceptable | 13.818 | **+18.0% regression** |
| relate | qw_pgq | outer_where | 20 | 13.902 | 14.219 | — | 13.625 | +2.0% acceptable | 14.237 | **-0.1% faster** |
| relate | qw_pgq | table_watchlist | 20 | 93.530 | 97.079 | — | 91.999 | +1.7% acceptable | 93.882 | +3.4% acceptable |
| relate | qw_pgq | values_watchlist | 20 | 91.713 | 92.945 | — | 90.380 | +1.5% acceptable | 92.301 | +0.7% acceptable |
| relate | qw_pgq | view_where | 20 | 14.582 | 15.106 | — | 14.314 | +1.9% acceptable | 14.674 | +2.9% acceptable |

