### Benchmark `3b5a92bbd8fe` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `7bdfb95c9518` on the same runner. The two releases alternated order across measurement blocks.

Latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**3 workloads with regressions · 16 with faster timings**

- ladybug/direct_cypher/lookup_miss (p50 +17.2%)
- relate/qw_cypher/lookup_miss (p50 +13.6%)
- relate/qw_pgq/view_where (p95 +20.3%)

#### Standalone graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.456 | 4.580 | — | 4.433 | +0.5% acceptable | 4.569 | +0.2% acceptable |
| ladybug | direct_cypher | lookup | 20 | 1.131 | 1.272 | — | 1.102 | +2.6% acceptable | 1.285 | **-1.0% faster** |
| ladybug | direct_cypher | lookup_miss | 20 | 0.437 | 0.566 | — | 0.373 | **+17.2% regression** | 0.610 | **-7.1% faster** |
| ladybug | qw_cypher | fanout | 20 | 5.577 | 5.746 | 1.25× | 5.576 | <+0.1% acceptable | 5.872 | **-2.1% faster** |
| ladybug | qw_cypher | lookup | 20 | 2.017 | 2.312 | 1.78× | 2.040 | **-1.1% faster** | 2.459 | **-6.0% faster** |
| ladybug | qw_cypher | lookup_miss | 20 | 1.985 | 2.383 | 4.55× | 2.028 | **-2.1% faster** | 2.672 | **-10.8% faster** |
| ladybug | qw_gql | fanout | 20 | 5.922 | 6.271 | 1.33× | 5.892 | +0.5% acceptable | 6.215 | +0.9% acceptable |
| ladybug | qw_gql | lookup | 20 | 2.346 | 2.962 | 2.08× | 2.317 | +1.3% acceptable | 2.759 | +7.3% acceptable |
| ladybug | qw_gql | lookup_miss | 20 | 2.346 | 3.006 | 5.37× | 2.256 | +4.0% acceptable | 2.953 | +1.8% acceptable |
| relate | direct_cypher | fanout | 20 | 11.046 | 11.320 | — | 11.022 | +0.2% acceptable | 11.324 | **>-0.1% faster** |
| relate | direct_cypher | lookup | 20 | 0.205 | 0.363 | — | 0.197 | +3.8% acceptable | 0.339 | +7.1% acceptable |
| relate | direct_cypher | lookup_miss | 20 | 0.334 | 0.495 | — | 0.339 | **-1.5% faster** | 0.451 | +9.9% acceptable |
| relate | qw_cypher | fanout | 20 | 11.628 | 11.982 | 1.05× | 11.671 | **-0.4% faster** | 11.975 | +0.1% acceptable |
| relate | qw_cypher | lookup | 20 | 2.308 | 3.013 | 11.29× | 2.207 | +4.6% acceptable | 2.831 | +6.4% acceptable |
| relate | qw_cypher | lookup_miss | 20 | 2.427 | 3.032 | 7.27× | 2.136 | **+13.6% regression** | 2.788 | +8.7% acceptable |
| relate | qw_gql | fanout | 20 | 12.086 | 12.538 | 1.09× | 11.926 | +1.3% acceptable | 12.460 | +0.6% acceptable |
| relate | qw_gql | lookup | 20 | 2.701 | 3.275 | 13.21× | 2.586 | +4.5% acceptable | 3.261 | +0.4% acceptable |
| relate | qw_gql | lookup_miss | 20 | 2.696 | 3.310 | 8.07× | 2.851 | **-5.4% faster** | 3.266 | +1.4% acceptable |

#### Hybrid SQL and graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 304.099 | 314.382 | — | 297.222 | +2.3% acceptable | 335.399 | **-6.3% faster** |
| ladybug | qw_pgq | graph_table_where | 20 | 7.163 | 7.444 | — | 7.074 | +1.3% acceptable | 7.653 | **-2.7% faster** |
| ladybug | qw_pgq | outer_where | 20 | 7.212 | 7.641 | — | 7.187 | +0.4% acceptable | 7.687 | **-0.6% faster** |
| ladybug | qw_pgq | table_watchlist | 20 | 15.413 | 17.092 | — | 15.482 | **-0.4% faster** | 16.481 | +3.7% acceptable |
| ladybug | qw_pgq | values_watchlist | 20 | 15.075 | 15.561 | — | 14.856 | +1.5% acceptable | 15.744 | **-1.2% faster** |
| ladybug | qw_pgq | view_where | 20 | 8.095 | 8.342 | — | 8.004 | +1.1% acceptable | 8.735 | **-4.5% faster** |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,905.060 | 4,996.785 | — | 4,921.220 | **-0.3% faster** | 4,963.564 | +0.7% acceptable |
| relate | qw_pgq | graph_table_where | 20 | 13.889 | 14.471 | — | 13.706 | +1.3% acceptable | 13.950 | +3.7% acceptable |
| relate | qw_pgq | outer_where | 20 | 13.846 | 14.260 | — | 13.678 | +1.2% acceptable | 14.008 | +1.8% acceptable |
| relate | qw_pgq | table_watchlist | 20 | 93.734 | 97.488 | — | 92.300 | +1.6% acceptable | 94.274 | +3.4% acceptable |
| relate | qw_pgq | values_watchlist | 20 | 92.467 | 98.043 | — | 91.410 | +1.2% acceptable | 92.755 | +5.7% acceptable |
| relate | qw_pgq | view_where | 20 | 14.847 | 18.088 | — | 14.622 | +1.5% acceptable | 15.040 | **+20.3% regression** |

