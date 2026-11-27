### Benchmark `6b5c59b1d0bc` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `54b2db6047ca` on the same runner. The two releases alternated order across measurement blocks.

Warm client latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**8 workloads with regressions · 12 with faster timings**

- ladybug/qw_cypher/lookup (p95 +12.8%)
- ladybug/qw_gql/lookup_miss (p95 +10.8%)
- relate/qw_cypher/lookup (p95 +26.8%)
- relate/qw_cypher/lookup_miss (p95 +28.0%)
- relate/qw_gql/fanout (p95 +14.9%)
- relate/qw_gql/lookup (p50 +12.2%, p95 +12.7%)
- relate/qw_gql/lookup_miss (p50 +19.6%, p95 +25.9%)
- relate/qw_pgq/graph_table_where (p95 +24.5%)

#### Standalone graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.358 | 4.481 | — | 4.378 | **-0.5% faster** | 4.435 | +1.0% acceptable |
| ladybug | direct_cypher | lookup | 20 | 1.044 | 1.120 | — | 1.037 | +0.7% acceptable | 1.094 | +2.4% acceptable |
| ladybug | direct_cypher | lookup_miss | 20 | 0.353 | 0.387 | — | 0.333 | +6.2% acceptable | 0.401 | **-3.5% faster** |
| ladybug | qw_cypher | fanout | 20 | 5.434 | 5.762 | 1.25× | 5.325 | +2.0% acceptable | 5.480 | +5.1% acceptable |
| ladybug | qw_cypher | lookup | 20 | 1.871 | 2.176 | 1.79× | 1.773 | +5.6% acceptable | 1.930 | **+12.8% regression** |
| ladybug | qw_cypher | lookup_miss | 20 | 1.845 | 2.024 | 5.22× | 1.748 | +5.5% acceptable | 1.893 | +7.0% acceptable |
| ladybug | qw_gql | fanout | 20 | 5.634 | 6.009 | 1.29× | 5.726 | **-1.6% faster** | 5.784 | +3.9% acceptable |
| ladybug | qw_gql | lookup | 20 | 1.998 | 2.314 | 1.91× | 2.047 | **-2.4% faster** | 2.225 | +4.0% acceptable |
| ladybug | qw_gql | lookup_miss | 20 | 1.947 | 2.371 | 5.51× | 2.041 | **-4.6% faster** | 2.141 | **+10.8% regression** |
| relate | direct_cypher | fanout | 20 | 10.813 | 11.494 | — | 10.837 | **-0.2% faster** | 11.069 | +3.8% acceptable |
| relate | direct_cypher | lookup | 20 | 0.192 | 0.300 | — | 0.180 | +6.2% acceptable | 0.308 | **-2.7% faster** |
| relate | direct_cypher | lookup_miss | 20 | 0.247 | 0.432 | — | 0.279 | **-11.5% faster** | 0.412 | +4.7% acceptable |
| relate | qw_cypher | fanout | 20 | 11.595 | 12.670 | 1.07× | 11.468 | +1.1% acceptable | 12.307 | +2.9% acceptable |
| relate | qw_cypher | lookup | 20 | 2.261 | 3.348 | 11.80× | 2.119 | +6.7% acceptable | 2.640 | **+26.8% regression** |
| relate | qw_cypher | lookup_miss | 20 | 2.202 | 3.325 | 8.93× | 2.212 | **-0.4% faster** | 2.599 | **+28.0% regression** |
| relate | qw_gql | fanout | 20 | 11.892 | 13.759 | 1.10× | 11.726 | +1.4% acceptable | 11.971 | **+14.9% regression** |
| relate | qw_gql | lookup | 20 | 2.383 | 3.028 | 12.43× | 2.124 | **+12.2% regression** | 2.687 | **+12.7% regression** |
| relate | qw_gql | lookup_miss | 20 | 2.519 | 3.446 | 10.22× | 2.107 | **+19.6% regression** | 2.738 | **+25.9% regression** |

#### Hybrid SQL and graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 291.287 | 303.488 | — | 294.639 | **-1.1% faster** | 303.430 | <+0.1% acceptable |
| ladybug | qw_pgq | graph_table_where | 20 | 6.769 | 7.176 | — | 6.579 | +2.9% acceptable | 7.112 | +0.9% acceptable |
| ladybug | qw_pgq | outer_where | 20 | 6.594 | 7.240 | — | 6.607 | **-0.2% faster** | 7.134 | +1.5% acceptable |
| ladybug | qw_pgq | table_watchlist | 20 | 15.106 | 16.596 | — | 14.776 | +2.2% acceptable | 15.535 | +6.8% acceptable |
| ladybug | qw_pgq | values_watchlist | 20 | 14.247 | 15.409 | — | 13.815 | +3.1% acceptable | 15.329 | +0.5% acceptable |
| ladybug | qw_pgq | view_where | 20 | 7.626 | 8.320 | — | 7.511 | +1.5% acceptable | 8.026 | +3.7% acceptable |
| relate | qw_pgq | full_scan_aggregate | 20 | 5,010.479 | 5,113.533 | — | 4,958.010 | +1.1% acceptable | 5,014.758 | +2.0% acceptable |
| relate | qw_pgq | graph_table_where | 20 | 13.636 | 17.071 | — | 13.465 | +1.3% acceptable | 13.717 | **+24.5% regression** |
| relate | qw_pgq | outer_where | 20 | 13.726 | 14.516 | — | 13.580 | +1.1% acceptable | 14.204 | +2.2% acceptable |
| relate | qw_pgq | table_watchlist | 20 | 92.675 | 95.652 | — | 91.618 | +1.2% acceptable | 92.525 | +3.4% acceptable |
| relate | qw_pgq | values_watchlist | 20 | 91.311 | 92.851 | — | 90.061 | +1.4% acceptable | 91.422 | +1.6% acceptable |
| relate | qw_pgq | view_where | 20 | 14.335 | 14.824 | — | 14.371 | **-0.3% faster** | 14.784 | +0.3% acceptable |

