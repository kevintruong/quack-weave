### Benchmark `0f030fd0e927` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `01ca5e7b471f` on the same runner. The two releases alternated order across measurement blocks.

The gate flags a series when p50 and p95 both rise by at least 20% and p50 increases by at least 0.25 ms.

#### Standalone graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.308 | 4.420 | — | 4.362 | -1.2% | 4.435 | -0.3% |
| ladybug | direct_cypher | lookup | 20 | 1.037 | 1.107 | — | 1.058 | -1.9% | 1.170 | -5.4% |
| ladybug | direct_cypher | lookup_miss | 20 | 0.344 | 0.421 | — | 0.336 | +2.2% | 0.415 | +1.3% |
| ladybug | qw_cypher | fanout | 20 | 5.467 | 5.659 | 1.27× | 5.325 | +2.7% | 5.511 | +2.7% |
| ladybug | qw_cypher | lookup | 20 | 1.844 | 2.051 | 1.78× | 1.801 | +2.4% | 1.999 | +2.6% |
| ladybug | qw_cypher | lookup_miss | 20 | 1.818 | 2.076 | 5.29× | 1.791 | +1.5% | 1.931 | +7.5% |
| ladybug | qw_gql | fanout | 20 | 10.736 | 11.351 | 2.49× | 10.702 | +0.3% | 11.084 | +2.4% |
| ladybug | qw_gql | lookup | 20 | 6.213 | 6.805 | 5.99× | 6.169 | +0.7% | 6.657 | +2.2% |
| ladybug | qw_gql | lookup_miss | 20 | 6.681 | 7.609 | 19.43× | 6.796 | -1.7% | 7.279 | +4.5% |
| relate | direct_cypher | fanout | 20 | 10.821 | 10.972 | — | 10.885 | -0.6% | 11.146 | -1.6% |
| relate | direct_cypher | lookup | 20 | 0.168 | 0.292 | — | 0.172 | -2.7% | 0.330 | -11.3% |
| relate | direct_cypher | lookup_miss | 20 | 0.268 | 0.376 | — | 0.274 | -2.4% | 0.426 | -11.7% |
| relate | qw_cypher | fanout | 20 | 11.406 | 11.604 | 1.05× | 11.300 | +0.9% | 11.402 | +1.8% |
| relate | qw_cypher | lookup | 20 | 1.948 | 2.492 | 11.62× | 1.996 | -2.4% | 2.505 | -0.5% |
| relate | qw_cypher | lookup_miss | 20 | 1.953 | 2.509 | 7.30× | 2.113 | -7.6% | 2.421 | +3.6% |
| relate | qw_gql | fanout | 20 | 16.593 | 16.981 | 1.53× | 16.913 | -1.9% | 17.211 | -1.3% |
| relate | qw_gql | lookup | 20 | 6.362 | 6.916 | 37.95× | 6.718 | -5.3% | 7.469 | -7.4% |
| relate | qw_gql | lookup_miss | 20 | 6.932 | 7.550 | 25.91× | 7.458 | -7.0% | 7.910 | -4.6% |

#### Hybrid SQL and graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 286.314 | 294.243 | — | 285.960 | +0.1% | 292.751 | +0.5% |
| ladybug | qw_pgq | graph_table_where | 20 | 6.857 | 7.112 | — | 6.660 | +3.0% | 7.141 | -0.4% |
| ladybug | qw_pgq | outer_where | 20 | 6.869 | 7.217 | — | 6.736 | +2.0% | 7.055 | +2.3% |
| ladybug | qw_pgq | table_watchlist | 20 | 15.052 | 15.561 | — | 14.888 | +1.1% | 16.048 | -3.0% |
| ladybug | qw_pgq | values_watchlist | 20 | 14.075 | 14.866 | — | 14.024 | +0.4% | 15.168 | -2.0% |
| ladybug | qw_pgq | view_where | 20 | 7.707 | 8.000 | — | 7.600 | +1.4% | 7.912 | +1.1% |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,973.684 | 5,028.960 | — | 4,941.152 | +0.7% | 4,972.693 | +1.1% |
| relate | qw_pgq | graph_table_where | 20 | 13.573 | 14.137 | — | 13.512 | +0.5% | 13.791 | +2.5% |
| relate | qw_pgq | outer_where | 20 | 13.593 | 13.775 | — | 13.517 | +0.6% | 13.896 | -0.9% |
| relate | qw_pgq | table_watchlist | 20 | 91.630 | 94.041 | — | 91.976 | -0.4% | 92.853 | +1.3% |
| relate | qw_pgq | values_watchlist | 20 | 90.546 | 91.965 | — | 90.723 | -0.2% | 91.492 | +0.5% |
| relate | qw_pgq | view_where | 20 | 14.314 | 22.822 | — | 14.267 | +0.3% | 14.775 | +54.5% |

