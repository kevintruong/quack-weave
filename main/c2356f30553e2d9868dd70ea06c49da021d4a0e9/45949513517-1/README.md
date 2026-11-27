### Benchmark `c2356f30553e` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `54b2db6047ca` on the same runner. The two releases alternated order across measurement blocks.

Warm client latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**2 workloads with regressions · 21 with faster timings**

- relate/qw_cypher/lookup (p95 +15.8%)
- relate/qw_pgq/table_watchlist (p95 +13.6%)

#### Standalone graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.259 | 4.332 | — | 4.267 | **-0.2% faster** | 4.344 | **-0.3% faster** |
| ladybug | direct_cypher | lookup | 20 | 0.996 | 1.033 | — | 1.003 | **-0.7% faster** | 1.043 | **-1.0% faster** |
| ladybug | direct_cypher | lookup_miss | 20 | 0.301 | 0.347 | — | 0.309 | **-2.7% faster** | 0.339 | +2.4% acceptable |
| ladybug | qw_cypher | fanout | 20 | 5.205 | 5.304 | 1.22× | 5.097 | +2.1% acceptable | 5.190 | +2.2% acceptable |
| ladybug | qw_cypher | lookup | 20 | 1.629 | 1.715 | 1.64× | 1.593 | +2.3% acceptable | 1.704 | +0.7% acceptable |
| ladybug | qw_cypher | lookup_miss | 20 | 1.612 | 1.706 | 5.36× | 1.566 | +2.9% acceptable | 1.722 | **-1.0% faster** |
| ladybug | qw_gql | fanout | 20 | 5.452 | 5.543 | 1.28× | 5.332 | +2.3% acceptable | 5.521 | +0.4% acceptable |
| ladybug | qw_gql | lookup | 20 | 1.794 | 1.891 | 1.80× | 1.776 | +1.1% acceptable | 1.921 | **-1.6% faster** |
| ladybug | qw_gql | lookup_miss | 20 | 1.774 | 1.850 | 5.90× | 1.764 | +0.6% acceptable | 2.023 | **-8.6% faster** |
| relate | direct_cypher | fanout | 20 | 10.567 | 10.689 | — | 10.597 | **-0.3% faster** | 10.831 | **-1.3% faster** |
| relate | direct_cypher | lookup | 20 | 0.154 | 0.204 | — | 0.166 | **-7.0% faster** | 0.287 | **-28.9% faster** |
| relate | direct_cypher | lookup_miss | 20 | 0.208 | 0.269 | — | 0.220 | **-5.4% faster** | 0.374 | **-28.1% faster** |
| relate | qw_cypher | fanout | 20 | 11.022 | 11.256 | 1.04× | 10.977 | +0.4% acceptable | 11.173 | +0.7% acceptable |
| relate | qw_cypher | lookup | 20 | 1.677 | 2.381 | 10.89× | 1.672 | +0.3% acceptable | 2.057 | **+15.8% regression** |
| relate | qw_cypher | lookup_miss | 20 | 1.695 | 2.331 | 8.14× | 1.666 | +1.7% acceptable | 2.129 | +9.5% acceptable |
| relate | qw_gql | fanout | 20 | 11.185 | 11.417 | 1.06× | 11.191 | **-0.1% faster** | 11.365 | +0.5% acceptable |
| relate | qw_gql | lookup | 20 | 1.855 | 2.447 | 12.04× | 1.882 | **-1.4% faster** | 2.380 | +2.8% acceptable |
| relate | qw_gql | lookup_miss | 20 | 1.870 | 2.263 | 8.98× | 1.922 | **-2.7% faster** | 2.291 | **-1.3% faster** |

#### Hybrid SQL and graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 243.479 | 257.696 | — | 255.236 | **-4.6% faster** | 282.786 | **-8.9% faster** |
| ladybug | qw_pgq | graph_table_where | 20 | 5.942 | 6.759 | — | 6.139 | **-3.2% faster** | 6.835 | **-1.1% faster** |
| ladybug | qw_pgq | outer_where | 20 | 6.010 | 6.763 | — | 6.055 | **-0.7% faster** | 6.930 | **-2.4% faster** |
| ladybug | qw_pgq | table_watchlist | 20 | 13.735 | 14.484 | — | 13.792 | **-0.4% faster** | 15.143 | **-4.4% faster** |
| ladybug | qw_pgq | values_watchlist | 20 | 12.762 | 13.356 | — | 12.967 | **-1.6% faster** | 14.617 | **-8.6% faster** |
| ladybug | qw_pgq | view_where | 20 | 6.798 | 7.659 | — | 7.034 | **-3.4% faster** | 7.666 | **-0.1% faster** |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,935.578 | 5,055.203 | — | 4,936.954 | **>-0.1% faster** | 5,105.214 | **-1.0% faster** |
| relate | qw_pgq | graph_table_where | 20 | 13.064 | 13.359 | — | 13.093 | **-0.2% faster** | 13.490 | **-1.0% faster** |
| relate | qw_pgq | outer_where | 20 | 13.215 | 13.563 | — | 13.136 | +0.6% acceptable | 13.478 | +0.6% acceptable |
| relate | qw_pgq | table_watchlist | 20 | 91.477 | 103.911 | — | 90.010 | +1.6% acceptable | 91.509 | **+13.6% regression** |
| relate | qw_pgq | values_watchlist | 20 | 90.135 | 91.777 | — | 89.053 | +1.2% acceptable | 91.111 | +0.7% acceptable |
| relate | qw_pgq | view_where | 20 | 13.850 | 14.125 | — | 13.810 | +0.3% acceptable | 14.156 | **-0.2% faster** |

