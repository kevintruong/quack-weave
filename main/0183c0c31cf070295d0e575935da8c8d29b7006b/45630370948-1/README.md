### Benchmark `0183c0c31cf0` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `7bdfb95c9518` on the same runner. The two releases alternated order across measurement blocks.

Latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**0 workloads with regressions · 22 with faster timings**

#### Standalone graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.248 | 4.319 | — | 4.263 | **-0.3% faster** | 4.314 | +0.1% acceptable |
| ladybug | direct_cypher | lookup | 20 | 1.022 | 1.046 | — | 1.022 | **>-0.1% faster** | 1.050 | **-0.3% faster** |
| ladybug | direct_cypher | lookup_miss | 20 | 0.321 | 0.359 | — | 0.326 | **-1.4% faster** | 0.368 | **-2.3% faster** |
| ladybug | qw_cypher | fanout | 20 | 5.213 | 5.336 | 1.23× | 5.236 | **-0.4% faster** | 5.295 | +0.8% acceptable |
| ladybug | qw_cypher | lookup | 20 | 1.721 | 1.805 | 1.68× | 1.720 | <+0.1% acceptable | 1.757 | +2.7% acceptable |
| ladybug | qw_cypher | lookup_miss | 20 | 1.691 | 1.793 | 5.26× | 1.697 | **-0.4% faster** | 1.738 | +3.2% acceptable |
| ladybug | qw_gql | fanout | 20 | 5.483 | 5.666 | 1.29× | 5.570 | **-1.6% faster** | 5.659 | +0.1% acceptable |
| ladybug | qw_gql | lookup | 20 | 1.915 | 2.049 | 1.87× | 1.975 | **-3.1% faster** | 2.053 | **-0.2% faster** |
| ladybug | qw_gql | lookup_miss | 20 | 1.906 | 2.015 | 5.93× | 1.959 | **-2.7% faster** | 2.014 | +0.1% acceptable |
| relate | direct_cypher | fanout | 20 | 10.631 | 10.743 | — | 10.683 | **-0.5% faster** | 10.792 | **-0.5% faster** |
| relate | direct_cypher | lookup | 20 | 0.149 | 0.197 | — | 0.156 | **-4.6% faster** | 0.198 | **-0.6% faster** |
| relate | direct_cypher | lookup_miss | 20 | 0.206 | 0.248 | — | 0.209 | **-1.4% faster** | 0.243 | +2.0% acceptable |
| relate | qw_cypher | fanout | 20 | 11.128 | 11.407 | 1.05× | 11.164 | **-0.3% faster** | 11.340 | +0.6% acceptable |
| relate | qw_cypher | lookup | 20 | 1.724 | 1.882 | 11.60× | 1.703 | +1.2% acceptable | 1.822 | +3.3% acceptable |
| relate | qw_cypher | lookup_miss | 20 | 1.695 | 1.825 | 8.24× | 1.685 | +0.6% acceptable | 1.821 | +0.3% acceptable |
| relate | qw_gql | fanout | 20 | 11.323 | 11.604 | 1.07× | 11.408 | **-0.7% faster** | 11.574 | +0.3% acceptable |
| relate | qw_gql | lookup | 20 | 1.885 | 2.030 | 12.68× | 1.918 | **-1.7% faster** | 2.071 | **-2.0% faster** |
| relate | qw_gql | lookup_miss | 20 | 1.894 | 2.009 | 9.21× | 1.891 | +0.2% acceptable | 2.060 | **-2.5% faster** |

#### Hybrid SQL and graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 207.205 | 215.412 | — | 205.805 | +0.7% acceptable | 213.617 | +0.8% acceptable |
| ladybug | qw_pgq | graph_table_where | 20 | 5.881 | 6.796 | — | 5.877 | +0.1% acceptable | 6.775 | +0.3% acceptable |
| ladybug | qw_pgq | outer_where | 20 | 5.925 | 6.701 | — | 5.953 | **-0.5% faster** | 6.783 | **-1.2% faster** |
| ladybug | qw_pgq | table_watchlist | 20 | 13.531 | 14.791 | — | 13.583 | **-0.4% faster** | 14.792 | **>-0.1% faster** |
| ladybug | qw_pgq | values_watchlist | 20 | 12.970 | 13.376 | — | 12.953 | +0.1% acceptable | 13.703 | **-2.4% faster** |
| ladybug | qw_pgq | view_where | 20 | 6.701 | 7.524 | — | 6.650 | +0.8% acceptable | 7.562 | **-0.5% faster** |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,989.659 | 5,028.023 | — | 4,893.673 | +2.0% acceptable | 4,957.654 | +1.4% acceptable |
| relate | qw_pgq | graph_table_where | 20 | 12.727 | 13.155 | — | 12.746 | **-0.1% faster** | 13.207 | **-0.4% faster** |
| relate | qw_pgq | outer_where | 20 | 12.713 | 13.153 | — | 12.763 | **-0.4% faster** | 13.364 | **-1.6% faster** |
| relate | qw_pgq | table_watchlist | 20 | 90.040 | 91.103 | — | 88.931 | +1.2% acceptable | 91.869 | **-0.8% faster** |
| relate | qw_pgq | values_watchlist | 20 | 89.295 | 90.602 | — | 88.176 | +1.3% acceptable | 89.958 | +0.7% acceptable |
| relate | qw_pgq | view_where | 20 | 13.576 | 14.009 | — | 13.521 | +0.4% acceptable | 13.953 | +0.4% acceptable |

