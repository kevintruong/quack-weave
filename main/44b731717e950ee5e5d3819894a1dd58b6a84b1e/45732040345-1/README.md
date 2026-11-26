### Benchmark `44b731717e95` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `7bdfb95c9518` on the same runner. The two releases alternated order across measurement blocks.

Latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**5 workloads with regressions · 6 with faster timings**

- relate/direct_cypher/lookup_miss (p50 +12.7%)
- relate/qw_cypher/lookup (p50 +10.4%, p95 +15.5%)
- relate/qw_cypher/lookup_miss (p95 +17.1%)
- relate/qw_gql/lookup (p95 +22.3%)
- relate/qw_gql/lookup_miss (p95 +23.8%)

#### Standalone graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.342 | 4.460 | — | 4.340 | <+0.1% acceptable | 4.378 | +1.9% acceptable |
| ladybug | direct_cypher | lookup | 20 | 1.050 | 1.089 | — | 1.049 | +0.1% acceptable | 1.095 | **-0.5% faster** |
| ladybug | direct_cypher | lookup_miss | 20 | 0.340 | 0.390 | — | 0.341 | **-0.2% faster** | 0.378 | +3.3% acceptable |
| ladybug | qw_cypher | fanout | 20 | 5.496 | 5.774 | 1.27× | 5.509 | **-0.2% faster** | 5.651 | +2.2% acceptable |
| ladybug | qw_cypher | lookup | 20 | 1.987 | 2.180 | 1.89× | 1.914 | +3.8% acceptable | 2.039 | +6.9% acceptable |
| ladybug | qw_cypher | lookup_miss | 20 | 1.915 | 2.139 | 5.63× | 1.906 | +0.5% acceptable | 2.007 | +6.6% acceptable |
| ladybug | qw_gql | fanout | 20 | 5.836 | 6.060 | 1.34× | 5.803 | +0.6% acceptable | 5.895 | +2.8% acceptable |
| ladybug | qw_gql | lookup | 20 | 2.212 | 2.370 | 2.11× | 2.117 | +4.5% acceptable | 2.322 | +2.1% acceptable |
| ladybug | qw_gql | lookup_miss | 20 | 2.134 | 2.371 | 6.27× | 2.104 | +1.4% acceptable | 2.361 | +0.4% acceptable |
| relate | direct_cypher | fanout | 20 | 10.876 | 11.134 | — | 10.755 | +1.1% acceptable | 10.979 | +1.4% acceptable |
| relate | direct_cypher | lookup | 20 | 0.185 | 0.296 | — | 0.177 | +4.3% acceptable | 0.275 | +7.7% acceptable |
| relate | direct_cypher | lookup_miss | 20 | 0.281 | 0.400 | — | 0.249 | **+12.7% regression** | 0.379 | +5.6% acceptable |
| relate | qw_cypher | fanout | 20 | 11.635 | 11.728 | 1.07× | 11.411 | +2.0% acceptable | 11.529 | +1.7% acceptable |
| relate | qw_cypher | lookup | 20 | 2.213 | 2.781 | 11.96× | 2.004 | **+10.4% regression** | 2.408 | **+15.5% regression** |
| relate | qw_cypher | lookup_miss | 20 | 2.164 | 2.753 | 7.71× | 1.977 | +9.4% acceptable | 2.351 | **+17.1% regression** |
| relate | qw_gql | fanout | 20 | 11.766 | 11.918 | 1.08× | 11.553 | +1.8% acceptable | 11.873 | +0.4% acceptable |
| relate | qw_gql | lookup | 20 | 2.331 | 2.861 | 12.60× | 2.144 | +8.7% acceptable | 2.339 | **+22.3% regression** |
| relate | qw_gql | lookup_miss | 20 | 2.334 | 2.916 | 8.31× | 2.146 | +8.8% acceptable | 2.355 | **+23.8% regression** |

#### Hybrid SQL and graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 294.274 | 303.265 | — | 288.804 | +1.9% acceptable | 301.099 | +0.7% acceptable |
| ladybug | qw_pgq | graph_table_where | 20 | 6.622 | 7.127 | — | 6.423 | +3.1% acceptable | 7.181 | **-0.7% faster** |
| ladybug | qw_pgq | outer_where | 20 | 6.667 | 7.161 | — | 6.573 | +1.4% acceptable | 7.147 | +0.2% acceptable |
| ladybug | qw_pgq | table_watchlist | 20 | 14.824 | 15.621 | — | 14.596 | +1.6% acceptable | 15.586 | +0.2% acceptable |
| ladybug | qw_pgq | values_watchlist | 20 | 14.142 | 14.885 | — | 13.709 | +3.2% acceptable | 15.198 | **-2.1% faster** |
| ladybug | qw_pgq | view_where | 20 | 7.620 | 8.047 | — | 7.537 | +1.1% acceptable | 8.061 | **-0.2% faster** |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,947.022 | 4,974.430 | — | 4,936.069 | +0.2% acceptable | 4,973.645 | <+0.1% acceptable |
| relate | qw_pgq | graph_table_where | 20 | 13.746 | 14.191 | — | 13.513 | +1.7% acceptable | 13.853 | +2.4% acceptable |
| relate | qw_pgq | outer_where | 20 | 13.768 | 14.236 | — | 13.517 | +1.9% acceptable | 13.827 | +3.0% acceptable |
| relate | qw_pgq | table_watchlist | 20 | 93.818 | 94.999 | — | 91.226 | +2.8% acceptable | 92.497 | +2.7% acceptable |
| relate | qw_pgq | values_watchlist | 20 | 92.158 | 93.035 | — | 89.783 | +2.6% acceptable | 90.402 | +2.9% acceptable |
| relate | qw_pgq | view_where | 20 | 14.775 | 15.181 | — | 14.340 | +3.0% acceptable | 14.599 | +4.0% acceptable |

