### Benchmark `f710395cba31` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `7bdfb95c9518` on the same runner. The two releases alternated order across measurement blocks.

Latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**6 workloads with regressions · 15 with faster timings**

- ladybug/qw_cypher/lookup_miss (p95 +14.2%)
- ladybug/qw_gql/fanout (p95 +14.5%)
- ladybug/qw_gql/lookup (p95 +67.0%)
- ladybug/qw_gql/lookup_miss (p95 +70.7%)
- relate/direct_cypher/lookup (p95 +19.6%)
- relate/direct_cypher/lookup_miss (p95 +12.1%)

#### Standalone graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.301 | 4.368 | — | 4.276 | +0.6% acceptable | 4.414 | **-1.0% faster** |
| ladybug | direct_cypher | lookup | 20 | 1.031 | 1.063 | — | 1.015 | +1.6% acceptable | 1.079 | **-1.5% faster** |
| ladybug | direct_cypher | lookup_miss | 20 | 0.313 | 0.361 | — | 0.314 | **-0.1% faster** | 0.359 | +0.7% acceptable |
| ladybug | qw_cypher | fanout | 20 | 5.359 | 5.482 | 1.25× | 5.198 | +3.1% acceptable | 5.385 | +1.8% acceptable |
| ladybug | qw_cypher | lookup | 20 | 1.796 | 1.960 | 1.74× | 1.704 | +5.4% acceptable | 1.865 | +5.0% acceptable |
| ladybug | qw_cypher | lookup_miss | 20 | 1.754 | 2.042 | 5.60× | 1.654 | +6.0% acceptable | 1.787 | **+14.2% regression** |
| ladybug | qw_gql | fanout | 20 | 5.774 | 6.450 | 1.34× | 5.480 | +5.4% acceptable | 5.631 | **+14.5% regression** |
| ladybug | qw_gql | lookup | 20 | 2.020 | 3.354 | 1.96× | 1.875 | +7.7% acceptable | 2.009 | **+67.0% regression** |
| ladybug | qw_gql | lookup_miss | 20 | 2.016 | 3.324 | 6.43× | 1.870 | +7.8% acceptable | 1.947 | **+70.7% regression** |
| relate | direct_cypher | fanout | 20 | 10.732 | 11.049 | — | 10.761 | **-0.3% faster** | 10.946 | +0.9% acceptable |
| relate | direct_cypher | lookup | 20 | 0.188 | 0.311 | — | 0.176 | +6.9% acceptable | 0.260 | **+19.6% regression** |
| relate | direct_cypher | lookup_miss | 20 | 0.257 | 0.411 | — | 0.260 | **-1.2% faster** | 0.367 | **+12.1% regression** |
| relate | qw_cypher | fanout | 20 | 11.188 | 11.351 | 1.04× | 11.200 | **-0.1% faster** | 11.455 | **-0.9% faster** |
| relate | qw_cypher | lookup | 20 | 1.849 | 2.096 | 9.81× | 1.857 | **-0.4% faster** | 2.248 | **-6.8% faster** |
| relate | qw_cypher | lookup_miss | 20 | 1.829 | 2.259 | 7.12× | 1.796 | +1.8% acceptable | 2.340 | **-3.5% faster** |
| relate | qw_gql | fanout | 20 | 11.425 | 11.546 | 1.06× | 11.483 | **-0.5% faster** | 12.479 | **-7.5% faster** |
| relate | qw_gql | lookup | 20 | 2.029 | 2.316 | 10.77× | 2.181 | **-7.0% faster** | 3.453 | **-32.9% faster** |
| relate | qw_gql | lookup_miss | 20 | 2.032 | 2.392 | 7.91× | 2.358 | **-13.8% faster** | 3.055 | **-21.7% faster** |

#### Hybrid SQL and graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 275.186 | 302.203 | — | 272.744 | +0.9% acceptable | 280.278 | +7.8% acceptable |
| ladybug | qw_pgq | graph_table_where | 20 | 6.577 | 7.250 | — | 6.311 | +4.2% acceptable | 6.893 | +5.2% acceptable |
| ladybug | qw_pgq | outer_where | 20 | 6.519 | 7.155 | — | 6.292 | +3.6% acceptable | 6.891 | +3.8% acceptable |
| ladybug | qw_pgq | table_watchlist | 20 | 14.396 | 15.393 | — | 14.161 | +1.7% acceptable | 15.297 | +0.6% acceptable |
| ladybug | qw_pgq | values_watchlist | 20 | 13.651 | 15.003 | — | 13.603 | +0.4% acceptable | 14.606 | +2.7% acceptable |
| ladybug | qw_pgq | view_where | 20 | 7.389 | 8.024 | — | 7.214 | +2.4% acceptable | 7.822 | +2.6% acceptable |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,947.358 | 5,009.254 | — | 4,920.200 | +0.6% acceptable | 4,993.260 | +0.3% acceptable |
| relate | qw_pgq | graph_table_where | 20 | 13.411 | 14.083 | — | 13.299 | +0.8% acceptable | 13.723 | +2.6% acceptable |
| relate | qw_pgq | outer_where | 20 | 13.424 | 13.629 | — | 13.339 | +0.6% acceptable | 14.252 | **-4.4% faster** |
| relate | qw_pgq | table_watchlist | 20 | 90.978 | 92.212 | — | 91.243 | **-0.3% faster** | 94.162 | **-2.1% faster** |
| relate | qw_pgq | values_watchlist | 20 | 90.095 | 92.336 | — | 90.108 | **>-0.1% faster** | 91.266 | +1.2% acceptable |
| relate | qw_pgq | view_where | 20 | 14.153 | 14.569 | — | 14.103 | +0.4% acceptable | 14.754 | **-1.3% faster** |

