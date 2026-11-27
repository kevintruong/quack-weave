### Benchmark `8e369ba42adb` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `4e20651be8a1` on the same runner. The two releases alternated order across measurement blocks.

Warm client latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**2 workloads with regressions · 13 with faster timings**

- relate/qw_cypher/lookup (p95 +23.6%)
- relate/qw_cypher/lookup_miss (p95 +30.2%)

#### Standalone graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.307 | 4.376 | — | 4.300 | +0.2% acceptable | 4.401 | **-0.6% faster** |
| ladybug | direct_cypher | lookup | 20 | 1.027 | 1.074 | — | 1.023 | +0.5% acceptable | 1.058 | +1.5% acceptable |
| ladybug | direct_cypher | lookup_miss | 20 | 0.329 | 0.353 | — | 0.334 | **-1.4% faster** | 0.384 | **-8.3% faster** |
| ladybug | qw_cypher | fanout | 20 | 5.313 | 5.426 | 1.23× | 5.301 | +0.2% acceptable | 5.378 | +0.9% acceptable |
| ladybug | qw_cypher | lookup | 20 | 1.773 | 1.868 | 1.73× | 1.765 | +0.4% acceptable | 1.849 | +1.0% acceptable |
| ladybug | qw_cypher | lookup_miss | 20 | 1.738 | 1.856 | 5.29× | 1.716 | +1.3% acceptable | 1.853 | +0.1% acceptable |
| ladybug | qw_gql | fanout | 20 | 5.604 | 5.796 | 1.30× | 5.552 | +1.0% acceptable | 5.689 | +1.9% acceptable |
| ladybug | qw_gql | lookup | 20 | 1.948 | 2.124 | 1.90× | 1.944 | +0.2% acceptable | 2.039 | +4.2% acceptable |
| ladybug | qw_gql | lookup_miss | 20 | 1.911 | 2.100 | 5.81× | 1.930 | **-1.0% faster** | 2.012 | +4.3% acceptable |
| relate | direct_cypher | fanout | 20 | 10.687 | 10.771 | — | 10.857 | **-1.6% faster** | 11.033 | **-2.4% faster** |
| relate | direct_cypher | lookup | 20 | 0.174 | 0.223 | — | 0.169 | +2.7% acceptable | 0.230 | **-2.9% faster** |
| relate | direct_cypher | lookup_miss | 20 | 0.235 | 0.314 | — | 0.263 | **-10.6% faster** | 0.336 | **-6.6% faster** |
| relate | qw_cypher | fanout | 20 | 11.319 | 11.529 | 1.06× | 11.277 | +0.4% acceptable | 11.562 | **-0.3% faster** |
| relate | qw_cypher | lookup | 20 | 1.803 | 2.551 | 10.37× | 1.774 | +1.6% acceptable | 2.064 | **+23.6% regression** |
| relate | qw_cypher | lookup_miss | 20 | 1.773 | 2.702 | 7.53× | 1.855 | **-4.4% faster** | 2.076 | **+30.2% regression** |
| relate | qw_gql | fanout | 20 | 11.539 | 11.642 | 1.08× | 11.465 | +0.6% acceptable | 11.725 | **-0.7% faster** |
| relate | qw_gql | lookup | 20 | 2.045 | 2.475 | 11.76× | 1.997 | +2.4% acceptable | 2.369 | +4.5% acceptable |
| relate | qw_gql | lookup_miss | 20 | 2.070 | 2.378 | 8.80× | 2.053 | +0.8% acceptable | 2.327 | +2.2% acceptable |

#### Hybrid SQL and graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 270.833 | 275.325 | — | 267.307 | +1.3% acceptable | 275.019 | +0.1% acceptable |
| ladybug | qw_pgq | graph_table_where | 20 | 6.296 | 6.943 | — | 6.289 | +0.1% acceptable | 6.903 | +0.6% acceptable |
| ladybug | qw_pgq | outer_where | 20 | 6.214 | 6.944 | — | 6.394 | **-2.8% faster** | 6.880 | +0.9% acceptable |
| ladybug | qw_pgq | table_watchlist | 20 | 14.325 | 15.210 | — | 14.377 | **-0.4% faster** | 14.964 | +1.6% acceptable |
| ladybug | qw_pgq | values_watchlist | 20 | 13.204 | 13.940 | — | 13.579 | **-2.8% faster** | 14.474 | **-3.7% faster** |
| ladybug | qw_pgq | view_where | 20 | 6.962 | 7.792 | — | 7.167 | **-2.9% faster** | 7.664 | +1.7% acceptable |
| relate | qw_pgq | full_scan_aggregate | 20 | 5,079.790 | 5,143.589 | — | 4,952.464 | +2.6% acceptable | 4,999.610 | +2.9% acceptable |
| relate | qw_pgq | graph_table_where | 20 | 13.522 | 13.790 | — | 13.388 | +1.0% acceptable | 13.723 | +0.5% acceptable |
| relate | qw_pgq | outer_where | 20 | 13.642 | 13.813 | — | 13.529 | +0.8% acceptable | 13.763 | +0.4% acceptable |
| relate | qw_pgq | table_watchlist | 20 | 93.027 | 94.326 | — | 91.604 | +1.6% acceptable | 92.530 | +1.9% acceptable |
| relate | qw_pgq | values_watchlist | 20 | 91.730 | 93.651 | — | 90.766 | +1.1% acceptable | 93.115 | +0.6% acceptable |
| relate | qw_pgq | view_where | 20 | 14.281 | 14.620 | — | 14.128 | +1.1% acceptable | 14.340 | +2.0% acceptable |

