### Benchmark `563a0b01c170` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `01ca5e7b471f` on the same runner. The two releases alternated order across measurement blocks.

The gate flags a series when p50 and p95 both rise by at least 20% and p50 increases by at least 0.25 ms.

#### Standalone graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.318 | 4.378 | — | 4.276 | +1.0% | 4.338 | +0.9% |
| ladybug | direct_cypher | lookup | 20 | 1.049 | 1.081 | — | 1.021 | +2.8% | 1.071 | +0.9% |
| ladybug | direct_cypher | lookup_miss | 20 | 0.326 | 0.396 | — | 0.311 | +4.6% | 0.376 | +5.4% |
| ladybug | qw_cypher | fanout | 20 | 5.402 | 5.589 | 1.25× | 5.317 | +1.6% | 5.439 | +2.8% |
| ladybug | qw_cypher | lookup | 20 | 1.844 | 1.925 | 1.76× | 1.826 | +1.0% | 1.956 | -1.6% |
| ladybug | qw_cypher | lookup_miss | 20 | 1.821 | 1.927 | 5.59× | 1.798 | +1.3% | 1.916 | +0.6% |
| ladybug | qw_gql | fanout | 20 | 10.601 | 10.840 | 2.45× | 10.412 | +1.8% | 10.782 | +0.5% |
| ladybug | qw_gql | lookup | 20 | 5.963 | 6.175 | 5.68× | 5.898 | +1.1% | 6.300 | -2.0% |
| ladybug | qw_gql | lookup_miss | 20 | 6.503 | 6.926 | 19.97× | 6.471 | +0.5% | 6.784 | +2.1% |
| relate | direct_cypher | fanout | 20 | 10.825 | 10.934 | — | 10.759 | +0.6% | 10.891 | +0.4% |
| relate | direct_cypher | lookup | 20 | 0.176 | 0.246 | — | 0.169 | +3.8% | 0.254 | -3.4% |
| relate | direct_cypher | lookup_miss | 20 | 0.260 | 0.362 | — | 0.255 | +2.0% | 0.331 | +9.5% |
| relate | qw_cypher | fanout | 20 | 11.453 | 11.790 | 1.06× | 11.429 | +0.2% | 11.579 | +1.8% |
| relate | qw_cypher | lookup | 20 | 2.018 | 2.437 | 11.50× | 1.923 | +5.0% | 2.440 | -0.1% |
| relate | qw_cypher | lookup_miss | 20 | 2.039 | 2.285 | 7.85× | 1.898 | +7.5% | 2.141 | +6.7% |
| relate | qw_gql | fanout | 20 | 16.602 | 17.086 | 1.53× | 16.556 | +0.3% | 18.164 | -5.9% |
| relate | qw_gql | lookup | 20 | 6.273 | 6.751 | 35.74× | 6.342 | -1.1% | 7.899 | -14.5% |
| relate | qw_gql | lookup_miss | 20 | 6.913 | 8.932 | 26.61× | 6.869 | +0.6% | 8.447 | +5.7% |

#### Hybrid SQL and graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 274.873 | 285.156 | — | 262.888 | +4.6% | 285.047 | +0.0% |
| ladybug | qw_pgq | graph_table_where | 20 | 6.474 | 7.008 | — | 6.230 | +3.9% | 7.007 | +0.0% |
| ladybug | qw_pgq | outer_where | 20 | 6.424 | 7.004 | — | 6.142 | +4.6% | 6.891 | +1.6% |
| ladybug | qw_pgq | table_watchlist | 20 | 14.232 | 14.854 | — | 14.075 | +1.1% | 14.762 | +0.6% |
| ladybug | qw_pgq | values_watchlist | 20 | 13.627 | 14.544 | — | 13.561 | +0.5% | 14.655 | -0.8% |
| ladybug | qw_pgq | view_where | 20 | 7.357 | 7.840 | — | 7.095 | +3.7% | 7.664 | +2.3% |
| relate | qw_pgq | full_scan_aggregate | 20 | 5,002.968 | 5,106.112 | — | 4,927.029 | +1.5% | 4,986.901 | +2.4% |
| relate | qw_pgq | graph_table_where | 20 | 13.569 | 13.816 | — | 13.413 | +1.2% | 13.721 | +0.7% |
| relate | qw_pgq | outer_where | 20 | 13.529 | 13.923 | — | 13.385 | +1.1% | 13.789 | +1.0% |
| relate | qw_pgq | table_watchlist | 20 | 92.041 | 93.768 | — | 91.562 | +0.5% | 92.097 | +1.8% |
| relate | qw_pgq | values_watchlist | 20 | 90.944 | 91.955 | — | 89.489 | +1.6% | 90.393 | +1.7% |
| relate | qw_pgq | view_where | 20 | 14.469 | 14.662 | — | 14.218 | +1.8% | 14.459 | +1.4% |

