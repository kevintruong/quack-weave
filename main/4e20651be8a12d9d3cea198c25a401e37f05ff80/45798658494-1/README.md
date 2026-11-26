### Benchmark `4e20651be8a1` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `d9e4a395038c` on the same runner. The two releases alternated order across measurement blocks.

Latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**4 workloads with regressions · 14 with faster timings**

- ladybug/direct_cypher/lookup_miss (p95 +15.9%)
- relate/direct_cypher/lookup (p95 +18.2%)
- relate/qw_gql/lookup (p95 +14.8%)
- relate/qw_gql/lookup_miss (p95 +16.2%)

#### Standalone graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.322 | 4.384 | — | 4.305 | +0.4% acceptable | 4.382 | +0.1% acceptable |
| ladybug | direct_cypher | lookup | 20 | 1.042 | 1.074 | — | 1.039 | +0.3% acceptable | 1.094 | **-1.9% faster** |
| ladybug | direct_cypher | lookup_miss | 20 | 0.325 | 0.436 | — | 0.342 | **-4.9% faster** | 0.376 | **+15.9% regression** |
| ladybug | qw_cypher | fanout | 20 | 5.381 | 5.470 | 1.25× | 5.306 | +1.4% acceptable | 5.443 | +0.5% acceptable |
| ladybug | qw_cypher | lookup | 20 | 1.782 | 1.851 | 1.71× | 1.757 | +1.4% acceptable | 1.813 | +2.1% acceptable |
| ladybug | qw_cypher | lookup_miss | 20 | 1.753 | 1.829 | 5.39× | 1.735 | +1.0% acceptable | 1.840 | **-0.6% faster** |
| ladybug | qw_gql | fanout | 20 | 5.650 | 5.813 | 1.31× | 5.534 | +2.1% acceptable | 5.740 | +1.3% acceptable |
| ladybug | qw_gql | lookup | 20 | 1.989 | 2.157 | 1.91× | 1.944 | +2.3% acceptable | 2.042 | +5.6% acceptable |
| ladybug | qw_gql | lookup_miss | 20 | 1.961 | 2.111 | 6.03× | 1.901 | +3.2% acceptable | 1.965 | +7.5% acceptable |
| relate | direct_cypher | fanout | 20 | 10.781 | 10.940 | — | 10.795 | **-0.1% faster** | 10.941 | **>-0.1% faster** |
| relate | direct_cypher | lookup | 20 | 0.173 | 0.261 | — | 0.175 | **-1.0% faster** | 0.221 | **+18.2% regression** |
| relate | direct_cypher | lookup_miss | 20 | 0.262 | 0.350 | — | 0.253 | +3.4% acceptable | 0.319 | +9.7% acceptable |
| relate | qw_cypher | fanout | 20 | 11.237 | 11.591 | 1.04× | 11.295 | **-0.5% faster** | 11.660 | **-0.6% faster** |
| relate | qw_cypher | lookup | 20 | 1.881 | 2.309 | 10.88× | 1.871 | +0.6% acceptable | 7.587 | **-69.6% faster** |
| relate | qw_cypher | lookup_miss | 20 | 1.929 | 2.316 | 7.36× | 1.851 | +4.2% acceptable | 2.442 | **-5.2% faster** |
| relate | qw_gql | fanout | 20 | 11.529 | 11.704 | 1.07× | 11.515 | +0.1% acceptable | 11.723 | **-0.2% faster** |
| relate | qw_gql | lookup | 20 | 2.132 | 2.614 | 12.33× | 2.020 | +5.6% acceptable | 2.276 | **+14.8% regression** |
| relate | qw_gql | lookup_miss | 20 | 2.207 | 2.607 | 8.42× | 2.081 | +6.0% acceptable | 2.244 | **+16.2% regression** |

#### Hybrid SQL and graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 273.604 | 284.250 | — | 267.087 | +2.4% acceptable | 276.573 | +2.8% acceptable |
| ladybug | qw_pgq | graph_table_where | 20 | 6.446 | 6.943 | — | 6.294 | +2.4% acceptable | 6.812 | +1.9% acceptable |
| ladybug | qw_pgq | outer_where | 20 | 6.437 | 6.850 | — | 6.233 | +3.3% acceptable | 6.850 | **>-0.1% faster** |
| ladybug | qw_pgq | table_watchlist | 20 | 14.523 | 15.096 | — | 14.113 | +2.9% acceptable | 15.011 | +0.6% acceptable |
| ladybug | qw_pgq | values_watchlist | 20 | 13.988 | 15.385 | — | 13.307 | +5.1% acceptable | 14.019 | +9.7% acceptable |
| ladybug | qw_pgq | view_where | 20 | 7.306 | 7.762 | — | 7.087 | +3.1% acceptable | 7.649 | +1.5% acceptable |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,949.571 | 4,985.229 | — | 4,946.428 | +0.1% acceptable | 5,008.361 | **-0.5% faster** |
| relate | qw_pgq | graph_table_where | 20 | 13.474 | 13.639 | — | 13.447 | +0.2% acceptable | 13.671 | **-0.2% faster** |
| relate | qw_pgq | outer_where | 20 | 13.455 | 13.771 | — | 13.493 | **-0.3% faster** | 13.808 | **-0.3% faster** |
| relate | qw_pgq | table_watchlist | 20 | 92.244 | 92.995 | — | 91.092 | +1.3% acceptable | 92.143 | +0.9% acceptable |
| relate | qw_pgq | values_watchlist | 20 | 90.766 | 92.253 | — | 89.514 | +1.4% acceptable | 90.496 | +1.9% acceptable |
| relate | qw_pgq | view_where | 20 | 14.158 | 14.433 | — | 14.162 | **>-0.1% faster** | 14.485 | **-0.4% faster** |

