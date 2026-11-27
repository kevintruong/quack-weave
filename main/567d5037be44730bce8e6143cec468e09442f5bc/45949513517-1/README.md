### Benchmark `567d5037be44` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `4e20651be8a1` on the same runner. The two releases alternated order across measurement blocks.

Warm client latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**2 workloads with regressions · 14 with faster timings**

- relate/direct_cypher/lookup (p95 +14.0%)
- relate/qw_pgq/view_where (p95 +48.6%)

#### Standalone graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.286 | 4.342 | — | 4.286 | <+0.1% acceptable | 4.334 | +0.2% acceptable |
| ladybug | direct_cypher | lookup | 20 | 1.035 | 1.064 | — | 1.031 | +0.4% acceptable | 1.055 | +0.9% acceptable |
| ladybug | direct_cypher | lookup_miss | 20 | 0.328 | 0.373 | — | 0.320 | +2.4% acceptable | 0.348 | +7.1% acceptable |
| ladybug | qw_cypher | fanout | 20 | 5.254 | 5.339 | 1.23× | 5.235 | +0.4% acceptable | 5.297 | +0.8% acceptable |
| ladybug | qw_cypher | lookup | 20 | 1.720 | 1.768 | 1.66× | 1.737 | **-1.0% faster** | 1.781 | **-0.7% faster** |
| ladybug | qw_cypher | lookup_miss | 20 | 1.678 | 1.737 | 5.12× | 1.710 | **-1.9% faster** | 1.749 | **-0.7% faster** |
| ladybug | qw_gql | fanout | 20 | 5.450 | 5.593 | 1.27× | 5.538 | **-1.6% faster** | 5.669 | **-1.3% faster** |
| ladybug | qw_gql | lookup | 20 | 1.839 | 1.966 | 1.78× | 1.940 | **-5.2% faster** | 2.062 | **-4.6% faster** |
| ladybug | qw_gql | lookup_miss | 20 | 1.837 | 1.952 | 5.60× | 1.908 | **-3.7% faster** | 2.263 | **-13.8% faster** |
| relate | direct_cypher | fanout | 20 | 10.703 | 10.943 | — | 10.764 | **-0.6% faster** | 10.987 | **-0.4% faster** |
| relate | direct_cypher | lookup | 20 | 0.169 | 0.225 | — | 0.166 | +1.7% acceptable | 0.197 | **+14.0% regression** |
| relate | direct_cypher | lookup_miss | 20 | 0.232 | 0.313 | — | 0.227 | +1.9% acceptable | 0.314 | **-0.3% faster** |
| relate | qw_cypher | fanout | 20 | 11.214 | 11.352 | 1.05× | 11.143 | +0.6% acceptable | 11.308 | +0.4% acceptable |
| relate | qw_cypher | lookup | 20 | 1.772 | 1.887 | 10.48× | 1.694 | +4.6% acceptable | 1.848 | +2.1% acceptable |
| relate | qw_cypher | lookup_miss | 20 | 1.768 | 1.865 | 7.63× | 1.699 | +4.1% acceptable | 1.855 | +0.5% acceptable |
| relate | qw_gql | fanout | 20 | 11.359 | 11.477 | 1.06× | 11.362 | **>-0.1% faster** | 11.492 | **-0.1% faster** |
| relate | qw_gql | lookup | 20 | 1.912 | 2.270 | 11.30× | 1.921 | **-0.5% faster** | 2.467 | **-8.0% faster** |
| relate | qw_gql | lookup_miss | 20 | 1.959 | 2.240 | 8.46× | 1.930 | +1.5% acceptable | 2.424 | **-7.6% faster** |

#### Hybrid SQL and graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 249.043 | 255.652 | — | 238.640 | +4.4% acceptable | 286.097 | **-10.6% faster** |
| ladybug | qw_pgq | graph_table_where | 20 | 6.133 | 6.926 | — | 6.064 | +1.2% acceptable | 6.939 | **-0.2% faster** |
| ladybug | qw_pgq | outer_where | 20 | 6.153 | 6.942 | — | 6.092 | +1.0% acceptable | 6.919 | +0.3% acceptable |
| ladybug | qw_pgq | table_watchlist | 20 | 14.096 | 15.042 | — | 13.862 | +1.7% acceptable | 14.942 | +0.7% acceptable |
| ladybug | qw_pgq | values_watchlist | 20 | 12.927 | 14.305 | — | 13.431 | **-3.7% faster** | 14.753 | **-3.0% faster** |
| ladybug | qw_pgq | view_where | 20 | 7.062 | 7.706 | — | 6.888 | +2.5% acceptable | 7.659 | +0.6% acceptable |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,980.414 | 5,061.623 | — | 4,946.206 | +0.7% acceptable | 5,051.811 | +0.2% acceptable |
| relate | qw_pgq | graph_table_where | 20 | 13.392 | 14.153 | — | 13.363 | +0.2% acceptable | 13.715 | +3.2% acceptable |
| relate | qw_pgq | outer_where | 20 | 13.413 | 13.840 | — | 13.395 | +0.1% acceptable | 13.596 | +1.8% acceptable |
| relate | qw_pgq | table_watchlist | 20 | 92.084 | 95.630 | — | 91.198 | +1.0% acceptable | 92.705 | +3.2% acceptable |
| relate | qw_pgq | values_watchlist | 20 | 90.708 | 100.213 | — | 90.293 | +0.5% acceptable | 91.622 | +9.4% acceptable |
| relate | qw_pgq | view_where | 20 | 14.143 | 22.037 | — | 14.179 | **-0.3% faster** | 14.833 | **+48.6% regression** |

