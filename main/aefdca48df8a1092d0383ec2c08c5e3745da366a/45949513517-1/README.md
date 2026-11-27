### Benchmark `aefdca48df8a` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `54b2db6047ca` on the same runner. The two releases alternated order across measurement blocks.

Warm client latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**0 workloads with regressions · 23 with faster timings**

#### Standalone graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.268 | 4.416 | — | 4.278 | **-0.3% faster** | 4.346 | +1.6% acceptable |
| ladybug | direct_cypher | lookup | 20 | 1.023 | 1.099 | — | 1.019 | +0.4% acceptable | 1.070 | +2.7% acceptable |
| ladybug | direct_cypher | lookup_miss | 20 | 0.317 | 0.385 | — | 0.315 | +0.8% acceptable | 0.366 | +5.3% acceptable |
| ladybug | qw_cypher | fanout | 20 | 5.292 | 5.536 | 1.24× | 5.269 | +0.4% acceptable | 5.403 | +2.5% acceptable |
| ladybug | qw_cypher | lookup | 20 | 1.722 | 1.999 | 1.68× | 1.746 | **-1.3% faster** | 1.837 | +8.8% acceptable |
| ladybug | qw_cypher | lookup_miss | 20 | 1.652 | 1.968 | 5.21× | 1.699 | **-2.8% faster** | 1.856 | +6.0% acceptable |
| ladybug | qw_gql | fanout | 20 | 5.512 | 5.769 | 1.29× | 5.500 | +0.2% acceptable | 5.819 | **-0.9% faster** |
| ladybug | qw_gql | lookup | 20 | 2.014 | 2.344 | 1.97× | 1.873 | +7.5% acceptable | 2.177 | +7.7% acceptable |
| ladybug | qw_gql | lookup_miss | 20 | 1.893 | 2.197 | 5.97× | 1.819 | +4.1% acceptable | 2.440 | **-10.0% faster** |
| relate | direct_cypher | fanout | 20 | 10.746 | 10.970 | — | 10.781 | **-0.3% faster** | 10.980 | **-0.1% faster** |
| relate | direct_cypher | lookup | 20 | 0.164 | 0.245 | — | 0.175 | **-6.2% faster** | 0.250 | **-2.3% faster** |
| relate | direct_cypher | lookup_miss | 20 | 0.242 | 0.344 | — | 0.246 | **-1.6% faster** | 0.382 | **-9.9% faster** |
| relate | qw_cypher | fanout | 20 | 11.035 | 11.221 | 1.03× | 11.196 | **-1.4% faster** | 15.942 | **-29.6% faster** |
| relate | qw_cypher | lookup | 20 | 1.706 | 1.878 | 10.40× | 1.830 | **-6.7% faster** | 2.432 | **-22.7% faster** |
| relate | qw_cypher | lookup_miss | 20 | 1.729 | 1.843 | 7.14× | 1.774 | **-2.6% faster** | 2.447 | **-24.7% faster** |
| relate | qw_gql | fanout | 20 | 11.187 | 11.388 | 1.04× | 11.278 | **-0.8% faster** | 11.473 | **-0.7% faster** |
| relate | qw_gql | lookup | 20 | 1.887 | 2.172 | 11.50× | 1.914 | **-1.4% faster** | 2.177 | **-0.2% faster** |
| relate | qw_gql | lookup_miss | 20 | 1.895 | 2.254 | 7.83× | 1.931 | **-1.8% faster** | 2.593 | **-13.1% faster** |

#### Hybrid SQL and graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 273.674 | 284.323 | — | 277.877 | **-1.5% faster** | 291.470 | **-2.5% faster** |
| ladybug | qw_pgq | graph_table_where | 20 | 6.615 | 7.003 | — | 6.646 | **-0.5% faster** | 7.010 | **-0.1% faster** |
| ladybug | qw_pgq | outer_where | 20 | 6.518 | 6.961 | — | 6.544 | **-0.4% faster** | 7.105 | **-2.0% faster** |
| ladybug | qw_pgq | table_watchlist | 20 | 14.516 | 15.685 | — | 14.533 | **-0.1% faster** | 15.699 | **-0.1% faster** |
| ladybug | qw_pgq | values_watchlist | 20 | 13.576 | 14.279 | — | 13.802 | **-1.6% faster** | 14.856 | **-3.9% faster** |
| ladybug | qw_pgq | view_where | 20 | 7.389 | 7.925 | — | 7.504 | **-1.5% faster** | 8.188 | **-3.2% faster** |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,994.522 | 5,062.613 | — | 4,931.852 | +1.3% acceptable | 4,980.114 | +1.7% acceptable |
| relate | qw_pgq | graph_table_where | 20 | 13.337 | 13.664 | — | 13.272 | +0.5% acceptable | 13.606 | +0.4% acceptable |
| relate | qw_pgq | outer_where | 20 | 13.389 | 13.735 | — | 13.286 | +0.8% acceptable | 13.628 | +0.8% acceptable |
| relate | qw_pgq | table_watchlist | 20 | 91.652 | 92.702 | — | 91.213 | +0.5% acceptable | 92.753 | **-0.1% faster** |
| relate | qw_pgq | values_watchlist | 20 | 90.394 | 91.736 | — | 90.345 | +0.1% acceptable | 92.104 | **-0.4% faster** |
| relate | qw_pgq | view_where | 20 | 13.989 | 14.313 | — | 14.068 | **-0.6% faster** | 14.641 | **-2.2% faster** |

