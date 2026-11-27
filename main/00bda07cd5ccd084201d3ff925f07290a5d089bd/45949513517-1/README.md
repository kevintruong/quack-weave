### Benchmark `00bda07cd5cc` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `54b2db6047ca` on the same runner. The two releases alternated order across measurement blocks.

Warm client latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**2 workloads with regressions · 19 with faster timings**

- ladybug/direct_cypher/lookup_miss (p95 +10.5%)
- relate/qw_pgq/graph_table_where (p95 +36.0%)

#### Standalone graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.340 | 4.401 | — | 4.340 | **>-0.1% faster** | 4.408 | **-0.2% faster** |
| ladybug | direct_cypher | lookup | 20 | 1.023 | 1.118 | — | 1.029 | **-0.6% faster** | 1.100 | +1.6% acceptable |
| ladybug | direct_cypher | lookup_miss | 20 | 0.333 | 0.448 | — | 0.342 | **-2.6% faster** | 0.406 | **+10.5% regression** |
| ladybug | qw_cypher | fanout | 20 | 5.311 | 5.395 | 1.22× | 5.253 | +1.1% acceptable | 5.391 | +0.1% acceptable |
| ladybug | qw_cypher | lookup | 20 | 1.743 | 1.829 | 1.70× | 1.750 | **-0.4% faster** | 1.915 | **-4.5% faster** |
| ladybug | qw_cypher | lookup_miss | 20 | 1.702 | 1.880 | 5.10× | 1.719 | **-1.0% faster** | 2.152 | **-12.6% faster** |
| ladybug | qw_gql | fanout | 20 | 5.484 | 5.711 | 1.26× | 5.504 | **-0.4% faster** | 5.682 | +0.5% acceptable |
| ladybug | qw_gql | lookup | 20 | 1.853 | 2.117 | 1.81× | 1.926 | **-3.8% faster** | 2.067 | +2.4% acceptable |
| ladybug | qw_gql | lookup_miss | 20 | 1.872 | 2.117 | 5.61× | 1.930 | **-3.0% faster** | 2.150 | **-1.5% faster** |
| relate | direct_cypher | fanout | 20 | 10.815 | 11.069 | — | 10.829 | **-0.1% faster** | 10.971 | +0.9% acceptable |
| relate | direct_cypher | lookup | 20 | 0.173 | 0.303 | — | 0.171 | +0.9% acceptable | 0.303 | **-0.1% faster** |
| relate | direct_cypher | lookup_miss | 20 | 0.284 | 0.379 | — | 0.272 | +4.6% acceptable | 0.374 | +1.2% acceptable |
| relate | qw_cypher | fanout | 20 | 11.275 | 11.626 | 1.04× | 11.245 | +0.3% acceptable | 11.382 | +2.1% acceptable |
| relate | qw_cypher | lookup | 20 | 1.980 | 2.496 | 11.45× | 1.880 | +5.3% acceptable | 2.442 | +2.2% acceptable |
| relate | qw_cypher | lookup_miss | 20 | 1.981 | 2.485 | 6.97× | 2.041 | **-3.0% faster** | 2.307 | +7.7% acceptable |
| relate | qw_gql | fanout | 20 | 11.272 | 11.459 | 1.04× | 11.408 | **-1.2% faster** | 12.355 | **-7.3% faster** |
| relate | qw_gql | lookup | 20 | 2.012 | 2.503 | 11.63× | 2.160 | **-6.9% faster** | 3.214 | **-22.1% faster** |
| relate | qw_gql | lookup_miss | 20 | 2.031 | 2.592 | 7.15× | 2.401 | **-15.4% faster** | 3.289 | **-21.2% faster** |

#### Hybrid SQL and graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 277.914 | 284.456 | — | 282.283 | **-1.5% faster** | 286.653 | **-0.8% faster** |
| ladybug | qw_pgq | graph_table_where | 20 | 6.667 | 6.986 | — | 6.754 | **-1.3% faster** | 7.049 | **-0.9% faster** |
| ladybug | qw_pgq | outer_where | 20 | 6.606 | 7.155 | — | 6.731 | **-1.8% faster** | 6.927 | +3.3% acceptable |
| ladybug | qw_pgq | table_watchlist | 20 | 14.650 | 15.771 | — | 14.632 | +0.1% acceptable | 15.742 | +0.2% acceptable |
| ladybug | qw_pgq | values_watchlist | 20 | 13.693 | 14.793 | — | 14.327 | **-4.4% faster** | 15.501 | **-4.6% faster** |
| ladybug | qw_pgq | view_where | 20 | 7.477 | 7.928 | — | 7.667 | **-2.5% faster** | 7.925 | <+0.1% acceptable |
| relate | qw_pgq | full_scan_aggregate | 20 | 5,033.408 | 5,134.424 | — | 4,929.051 | +2.1% acceptable | 4,974.853 | +3.2% acceptable |
| relate | qw_pgq | graph_table_where | 20 | 13.433 | 18.645 | — | 13.372 | +0.5% acceptable | 13.708 | **+36.0% regression** |
| relate | qw_pgq | outer_where | 20 | 13.516 | 13.776 | — | 13.380 | +1.0% acceptable | 13.558 | +1.6% acceptable |
| relate | qw_pgq | table_watchlist | 20 | 92.613 | 94.218 | — | 91.634 | +1.1% acceptable | 92.562 | +1.8% acceptable |
| relate | qw_pgq | values_watchlist | 20 | 91.743 | 92.734 | — | 90.126 | +1.8% acceptable | 91.090 | +1.8% acceptable |
| relate | qw_pgq | view_where | 20 | 14.203 | 14.499 | — | 14.073 | +0.9% acceptable | 14.391 | +0.7% acceptable |

