### Benchmark `2d3cfecd434e` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `4e20651be8a1` on the same runner. The two releases alternated order across measurement blocks.

Warm client latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**4 workloads with regressions · 21 with faster timings**

- relate/direct_cypher/lookup (p95 +20.9%)
- relate/qw_cypher/lookup_miss (p95 +11.9%)
- relate/qw_pgq/table_watchlist (p95 +21.2%)
- relate/qw_pgq/view_where (p95 +13.7%)

#### Standalone graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.297 | 4.405 | — | 4.333 | **-0.8% faster** | 4.481 | **-1.7% faster** |
| ladybug | direct_cypher | lookup | 20 | 1.022 | 1.055 | — | 1.029 | **-0.7% faster** | 1.205 | **-12.5% faster** |
| ladybug | direct_cypher | lookup_miss | 20 | 0.320 | 0.364 | — | 0.330 | **-2.9% faster** | 0.534 | **-31.8% faster** |
| ladybug | qw_cypher | fanout | 20 | 5.305 | 5.533 | 1.23× | 5.321 | **-0.3% faster** | 5.520 | +0.2% acceptable |
| ladybug | qw_cypher | lookup | 20 | 1.763 | 1.911 | 1.72× | 1.689 | +4.4% acceptable | 1.895 | +0.8% acceptable |
| ladybug | qw_cypher | lookup_miss | 20 | 1.733 | 1.845 | 5.41× | 1.676 | +3.4% acceptable | 1.937 | **-4.8% faster** |
| ladybug | qw_gql | fanout | 20 | 5.571 | 5.671 | 1.30× | 5.565 | +0.1% acceptable | 5.947 | **-4.6% faster** |
| ladybug | qw_gql | lookup | 20 | 1.958 | 2.025 | 1.92× | 1.928 | +1.6% acceptable | 2.257 | **-10.3% faster** |
| ladybug | qw_gql | lookup_miss | 20 | 1.943 | 2.014 | 6.07× | 1.920 | +1.2% acceptable | 2.512 | **-19.8% faster** |
| relate | direct_cypher | fanout | 20 | 10.852 | 11.025 | — | 10.814 | +0.4% acceptable | 10.924 | +0.9% acceptable |
| relate | direct_cypher | lookup | 20 | 0.179 | 0.294 | — | 0.177 | +1.3% acceptable | 0.243 | **+20.9% regression** |
| relate | direct_cypher | lookup_miss | 20 | 0.246 | 0.405 | — | 0.251 | **-2.3% faster** | 0.383 | +5.8% acceptable |
| relate | qw_cypher | fanout | 20 | 11.439 | 12.109 | 1.05× | 11.328 | +1.0% acceptable | 11.620 | +4.2% acceptable |
| relate | qw_cypher | lookup | 20 | 1.666 | 2.717 | 9.30× | 1.904 | **-12.5% faster** | 2.538 | +7.1% acceptable |
| relate | qw_cypher | lookup_miss | 20 | 1.664 | 2.900 | 6.78× | 1.869 | **-11.0% faster** | 2.592 | **+11.9% regression** |
| relate | qw_gql | fanout | 20 | 11.461 | 12.423 | 1.06× | 11.652 | **-1.6% faster** | 12.053 | +3.1% acceptable |
| relate | qw_gql | lookup | 20 | 1.966 | 2.421 | 10.97× | 2.088 | **-5.9% faster** | 2.742 | **-11.7% faster** |
| relate | qw_gql | lookup_miss | 20 | 1.973 | 3.018 | 8.03× | 2.241 | **-12.0% faster** | 3.024 | **-0.2% faster** |

#### Hybrid SQL and graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 252.770 | 287.632 | — | 284.050 | **-11.0% faster** | 294.899 | **-2.5% faster** |
| ladybug | qw_pgq | graph_table_where | 20 | 6.249 | 7.024 | — | 6.342 | **-1.5% faster** | 7.104 | **-1.1% faster** |
| ladybug | qw_pgq | outer_where | 20 | 6.323 | 6.985 | — | 6.522 | **-3.0% faster** | 6.900 | +1.2% acceptable |
| ladybug | qw_pgq | table_watchlist | 20 | 14.303 | 15.383 | — | 14.541 | **-1.6% faster** | 15.485 | **-0.7% faster** |
| ladybug | qw_pgq | values_watchlist | 20 | 13.448 | 14.561 | — | 13.825 | **-2.7% faster** | 14.959 | **-2.7% faster** |
| ladybug | qw_pgq | view_where | 20 | 7.389 | 7.818 | — | 7.502 | **-1.5% faster** | 7.954 | **-1.7% faster** |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,976.996 | 5,040.837 | — | 4,946.799 | +0.6% acceptable | 4,979.407 | +1.2% acceptable |
| relate | qw_pgq | graph_table_where | 20 | 13.388 | 14.370 | — | 13.410 | **-0.2% faster** | 13.692 | +4.9% acceptable |
| relate | qw_pgq | outer_where | 20 | 13.595 | 14.844 | — | 13.233 | +2.7% acceptable | 13.617 | +9.0% acceptable |
| relate | qw_pgq | table_watchlist | 20 | 91.756 | 111.910 | — | 91.212 | +0.6% acceptable | 92.322 | **+21.2% regression** |
| relate | qw_pgq | values_watchlist | 20 | 90.312 | 92.471 | — | 89.530 | +0.9% acceptable | 91.378 | +1.2% acceptable |
| relate | qw_pgq | view_where | 20 | 14.405 | 16.549 | — | 14.096 | +2.2% acceptable | 14.561 | **+13.7% regression** |

