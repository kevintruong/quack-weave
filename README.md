# Latest main benchmark report

[Archived attempt and raw data](main/2ff32086ea58e8858ec419e841a355f940394b60/45547865907-1/)

### Benchmark `2ff32086ea58` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `01ca5e7b471f` on the same runner. The two releases alternated order across measurement blocks.

The gate flags a series when p50 and p95 both rise by at least 20% and p50 increases by at least 0.25 ms.

#### Standalone graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.351 | 4.480 | — | 4.454 | -2.3% | 4.592 | -2.4% |
| ladybug | direct_cypher | lookup | 20 | 1.058 | 1.176 | — | 1.138 | -7.0% | 1.240 | -5.2% |
| ladybug | direct_cypher | lookup_miss | 20 | 0.361 | 0.429 | — | 0.433 | -16.7% | 0.600 | -28.6% |
| ladybug | qw_cypher | fanout | 20 | 5.435 | 5.661 | 1.25× | 5.771 | -5.8% | 6.107 | -7.3% |
| ladybug | qw_cypher | lookup | 20 | 1.882 | 2.149 | 1.78× | 2.165 | -13.1% | 2.770 | -22.4% |
| ladybug | qw_cypher | lookup_miss | 20 | 1.819 | 2.133 | 5.04× | 2.160 | -15.8% | 2.617 | -18.5% |
| ladybug | qw_gql | fanout | 20 | 5.845 | 6.051 | 1.34× | 11.692 | -50.0% | 12.789 | -52.7% |
| ladybug | qw_gql | lookup | 20 | 2.147 | 2.579 | 2.03× | 7.046 | -69.5% | 7.850 | -67.1% |
| ladybug | qw_gql | lookup_miss | 20 | 2.151 | 2.685 | 5.96× | 7.521 | -71.4% | 8.708 | -69.2% |
| relate | direct_cypher | fanout | 20 | 10.902 | 11.117 | — | 10.913 | -0.1% | 11.195 | -0.7% |
| relate | direct_cypher | lookup | 20 | 0.173 | 0.320 | — | 0.200 | -13.6% | 0.345 | -7.5% |
| relate | direct_cypher | lookup_miss | 20 | 0.265 | 0.410 | — | 0.306 | -13.7% | 0.464 | -11.7% |
| relate | qw_cypher | fanout | 20 | 11.351 | 11.431 | 1.04× | 11.477 | -1.1% | 13.177 | -13.3% |
| relate | qw_cypher | lookup | 20 | 1.949 | 2.377 | 11.28× | 2.212 | -11.9% | 3.712 | -36.0% |
| relate | qw_cypher | lookup_miss | 20 | 1.967 | 2.343 | 7.44× | 2.143 | -8.2% | 2.833 | -17.3% |
| relate | qw_gql | fanout | 20 | 11.592 | 11.924 | 1.06× | 17.006 | -31.8% | 17.973 | -33.7% |
| relate | qw_gql | lookup | 20 | 2.273 | 2.947 | 13.15× | 6.895 | -67.0% | 7.983 | -63.1% |
| relate | qw_gql | lookup_miss | 20 | 2.328 | 2.827 | 8.80× | 7.378 | -68.4% | 9.918 | -71.5% |

#### Hybrid SQL and graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 280.251 | 295.343 | — | 300.722 | -6.8% | 318.318 | -7.2% |
| ladybug | qw_pgq | graph_table_where | 20 | 6.855 | 7.265 | — | 7.225 | -5.1% | 7.511 | -3.3% |
| ladybug | qw_pgq | outer_where | 20 | 6.870 | 7.397 | — | 7.245 | -5.2% | 7.516 | -1.6% |
| ladybug | qw_pgq | table_watchlist | 20 | 14.796 | 15.801 | — | 15.651 | -5.5% | 16.612 | -4.9% |
| ladybug | qw_pgq | values_watchlist | 20 | 14.485 | 15.114 | — | 14.895 | -2.7% | 16.529 | -8.6% |
| ladybug | qw_pgq | view_where | 20 | 7.812 | 8.300 | — | 8.149 | -4.1% | 8.751 | -5.1% |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,969.483 | 5,049.644 | — | 4,941.427 | +0.6% | 5,002.893 | +0.9% |
| relate | qw_pgq | graph_table_where | 20 | 13.587 | 14.100 | — | 13.474 | +0.8% | 13.743 | +2.6% |
| relate | qw_pgq | outer_where | 20 | 13.568 | 13.862 | — | 13.459 | +0.8% | 13.672 | +1.4% |
| relate | qw_pgq | table_watchlist | 20 | 92.271 | 93.627 | — | 91.572 | +0.8% | 92.592 | +1.1% |
| relate | qw_pgq | values_watchlist | 20 | 90.668 | 95.715 | — | 90.358 | +0.3% | 93.490 | +2.4% |
| relate | qw_pgq | view_where | 20 | 14.413 | 18.783 | — | 14.311 | +0.7% | 14.533 | +29.2% |
