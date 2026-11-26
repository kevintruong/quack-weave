### Benchmark `dfbc44985f6a` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `7bdfb95c9518` on the same runner. The two releases alternated order across measurement blocks.

Latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**0 workloads with regressions · 29 with faster timings**

#### Standalone graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.263 | 4.328 | — | 4.278 | **-0.3% faster** | 4.353 | **-0.6% faster** |
| ladybug | direct_cypher | lookup | 20 | 1.011 | 1.051 | — | 1.010 | +0.1% acceptable | 1.063 | **-1.1% faster** |
| ladybug | direct_cypher | lookup_miss | 20 | 0.313 | 0.368 | — | 0.317 | **-1.2% faster** | 0.387 | **-4.8% faster** |
| ladybug | qw_cypher | fanout | 20 | 5.232 | 5.349 | 1.23× | 5.321 | **-1.7% faster** | 5.476 | **-2.3% faster** |
| ladybug | qw_cypher | lookup | 20 | 1.696 | 1.755 | 1.68× | 1.796 | **-5.6% faster** | 1.955 | **-10.2% faster** |
| ladybug | qw_cypher | lookup_miss | 20 | 1.661 | 1.739 | 5.31× | 1.735 | **-4.3% faster** | 2.017 | **-13.8% faster** |
| ladybug | qw_gql | fanout | 20 | 5.504 | 5.646 | 1.29× | 5.586 | **-1.5% faster** | 5.796 | **-2.6% faster** |
| ladybug | qw_gql | lookup | 20 | 1.883 | 1.986 | 1.86× | 1.967 | **-4.3% faster** | 2.191 | **-9.4% faster** |
| ladybug | qw_gql | lookup_miss | 20 | 1.842 | 1.993 | 5.89× | 1.927 | **-4.4% faster** | 2.084 | **-4.4% faster** |
| relate | direct_cypher | fanout | 20 | 10.754 | 10.886 | — | 10.677 | +0.7% acceptable | 10.917 | **-0.3% faster** |
| relate | direct_cypher | lookup | 20 | 0.163 | 0.239 | — | 0.174 | **-6.7% faster** | 0.276 | **-13.5% faster** |
| relate | direct_cypher | lookup_miss | 20 | 0.251 | 0.327 | — | 0.260 | **-3.4% faster** | 0.379 | **-13.9% faster** |
| relate | qw_cypher | fanout | 20 | 11.055 | 11.215 | 1.03× | 11.309 | **-2.3% faster** | 11.483 | **-2.3% faster** |
| relate | qw_cypher | lookup | 20 | 1.747 | 2.057 | 10.74× | 1.843 | **-5.2% faster** | 2.311 | **-11.0% faster** |
| relate | qw_cypher | lookup_miss | 20 | 1.800 | 2.025 | 7.17× | 1.906 | **-5.6% faster** | 2.219 | **-8.7% faster** |
| relate | qw_gql | fanout | 20 | 11.304 | 11.557 | 1.05× | 11.515 | **-1.8% faster** | 11.733 | **-1.5% faster** |
| relate | qw_gql | lookup | 20 | 2.001 | 2.546 | 12.30× | 2.098 | **-4.6% faster** | 2.605 | **-2.3% faster** |
| relate | qw_gql | lookup_miss | 20 | 2.035 | 2.305 | 8.11× | 2.135 | **-4.7% faster** | 2.464 | **-6.5% faster** |

#### Hybrid SQL and graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 267.443 | 274.029 | — | 275.404 | **-2.9% faster** | 280.207 | **-2.2% faster** |
| ladybug | qw_pgq | graph_table_where | 20 | 6.308 | 6.891 | — | 6.544 | **-3.6% faster** | 6.993 | **-1.5% faster** |
| ladybug | qw_pgq | outer_where | 20 | 6.420 | 6.865 | — | 6.536 | **-1.8% faster** | 6.946 | **-1.2% faster** |
| ladybug | qw_pgq | table_watchlist | 20 | 14.262 | 15.082 | — | 14.468 | **-1.4% faster** | 14.896 | +1.2% acceptable |
| ladybug | qw_pgq | values_watchlist | 20 | 13.525 | 14.394 | — | 13.584 | **-0.4% faster** | 14.445 | **-0.4% faster** |
| ladybug | qw_pgq | view_where | 20 | 7.098 | 7.655 | — | 7.209 | **-1.5% faster** | 7.796 | **-1.8% faster** |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,873.624 | 4,931.298 | — | 4,903.911 | **-0.6% faster** | 4,959.175 | **-0.6% faster** |
| relate | qw_pgq | graph_table_where | 20 | 13.196 | 13.401 | — | 13.366 | **-1.3% faster** | 13.892 | **-3.5% faster** |
| relate | qw_pgq | outer_where | 20 | 13.228 | 13.592 | — | 13.356 | **-1.0% faster** | 15.378 | **-11.6% faster** |
| relate | qw_pgq | table_watchlist | 20 | 90.723 | 92.699 | — | 90.577 | +0.2% acceptable | 93.004 | **-0.3% faster** |
| relate | qw_pgq | values_watchlist | 20 | 90.145 | 99.211 | — | 89.396 | +0.8% acceptable | 95.503 | +3.9% acceptable |
| relate | qw_pgq | view_where | 20 | 13.972 | 15.422 | — | 14.124 | **-1.1% faster** | 18.731 | **-17.7% faster** |

