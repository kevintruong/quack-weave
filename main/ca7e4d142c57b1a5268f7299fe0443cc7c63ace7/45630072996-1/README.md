### Benchmark `ca7e4d142c57` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `7bdfb95c9518` on the same runner. The two releases alternated order across measurement blocks.

Latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**1 workloads with regressions · 15 with faster timings**

- relate/qw_cypher/lookup_miss (p95 +14.4%)

#### Standalone graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.315 | 4.383 | — | 4.322 | **-0.2% faster** | 4.379 | +0.1% acceptable |
| ladybug | direct_cypher | lookup | 20 | 1.039 | 1.101 | — | 1.030 | +0.8% acceptable | 1.071 | +2.8% acceptable |
| ladybug | direct_cypher | lookup_miss | 20 | 0.345 | 0.379 | — | 0.334 | +3.4% acceptable | 0.378 | +0.3% acceptable |
| ladybug | qw_cypher | fanout | 20 | 5.340 | 5.549 | 1.24× | 5.373 | **-0.6% faster** | 5.532 | +0.3% acceptable |
| ladybug | qw_cypher | lookup | 20 | 1.857 | 2.002 | 1.79× | 1.851 | +0.3% acceptable | 1.992 | +0.5% acceptable |
| ladybug | qw_cypher | lookup_miss | 20 | 1.786 | 1.988 | 5.17× | 1.797 | **-0.6% faster** | 1.975 | +0.7% acceptable |
| ladybug | qw_gql | fanout | 20 | 5.560 | 5.848 | 1.29× | 5.540 | +0.4% acceptable | 5.636 | +3.8% acceptable |
| ladybug | qw_gql | lookup | 20 | 1.922 | 2.253 | 1.85× | 1.916 | +0.3% acceptable | 2.068 | +8.9% acceptable |
| ladybug | qw_gql | lookup_miss | 20 | 1.890 | 2.172 | 5.47× | 1.894 | **-0.2% faster** | 2.073 | +4.8% acceptable |
| relate | direct_cypher | fanout | 20 | 10.721 | 10.899 | — | 10.763 | **-0.4% faster** | 11.003 | **-0.9% faster** |
| relate | direct_cypher | lookup | 20 | 0.170 | 0.245 | — | 0.170 | **-0.1% faster** | 0.278 | **-11.8% faster** |
| relate | direct_cypher | lookup_miss | 20 | 0.255 | 0.352 | — | 0.255 | **-0.2% faster** | 0.392 | **-10.3% faster** |
| relate | qw_cypher | fanout | 20 | 11.358 | 11.793 | 1.06× | 11.255 | +0.9% acceptable | 11.521 | +2.4% acceptable |
| relate | qw_cypher | lookup | 20 | 1.989 | 2.575 | 11.68× | 1.941 | +2.5% acceptable | 2.409 | +6.9% acceptable |
| relate | qw_cypher | lookup_miss | 20 | 1.926 | 2.664 | 7.56× | 1.931 | **-0.2% faster** | 2.328 | **+14.4% regression** |
| relate | qw_gql | fanout | 20 | 11.500 | 11.627 | 1.07× | 11.514 | **-0.1% faster** | 11.675 | **-0.4% faster** |
| relate | qw_gql | lookup | 20 | 2.047 | 2.480 | 12.02× | 2.061 | **-0.7% faster** | 2.641 | **-6.1% faster** |
| relate | qw_gql | lookup_miss | 20 | 2.115 | 2.606 | 8.30× | 2.189 | **-3.4% faster** | 2.542 | +2.5% acceptable |

#### Hybrid SQL and graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 274.415 | 283.800 | — | 273.118 | +0.5% acceptable | 282.361 | +0.5% acceptable |
| ladybug | qw_pgq | graph_table_where | 20 | 6.644 | 7.081 | — | 6.382 | +4.1% acceptable | 6.997 | +1.2% acceptable |
| ladybug | qw_pgq | outer_where | 20 | 6.597 | 7.018 | — | 6.358 | +3.8% acceptable | 6.914 | +1.5% acceptable |
| ladybug | qw_pgq | table_watchlist | 20 | 14.430 | 15.297 | — | 14.276 | +1.1% acceptable | 14.918 | +2.5% acceptable |
| ladybug | qw_pgq | values_watchlist | 20 | 13.654 | 14.658 | — | 13.520 | +1.0% acceptable | 14.250 | +2.9% acceptable |
| ladybug | qw_pgq | view_where | 20 | 7.437 | 7.893 | — | 7.266 | +2.3% acceptable | 7.804 | +1.1% acceptable |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,941.487 | 4,990.330 | — | 4,930.713 | +0.2% acceptable | 5,010.661 | **-0.4% faster** |
| relate | qw_pgq | graph_table_where | 20 | 13.523 | 14.555 | — | 13.489 | +0.3% acceptable | 13.840 | +5.2% acceptable |
| relate | qw_pgq | outer_where | 20 | 13.472 | 13.739 | — | 13.568 | **-0.7% faster** | 13.769 | **-0.2% faster** |
| relate | qw_pgq | table_watchlist | 20 | 92.138 | 94.704 | — | 91.373 | +0.8% acceptable | 93.835 | +0.9% acceptable |
| relate | qw_pgq | values_watchlist | 20 | 90.345 | 92.116 | — | 90.356 | **>-0.1% faster** | 90.732 | +1.5% acceptable |
| relate | qw_pgq | view_where | 20 | 14.225 | 14.599 | — | 14.256 | **-0.2% faster** | 14.710 | **-0.8% faster** |

