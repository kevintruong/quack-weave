### Benchmark `cf77c253259c` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `7bdfb95c9518` on the same runner. The two releases alternated order across measurement blocks.

Latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**1 workloads with regressions · 19 with faster timings**

- relate/qw_cypher/lookup (p95 +15.4%)

#### Standalone graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.276 | 4.355 | — | 4.303 | **-0.6% faster** | 4.360 | **-0.1% faster** |
| ladybug | direct_cypher | lookup | 20 | 1.045 | 1.085 | — | 1.034 | +1.1% acceptable | 1.089 | **-0.4% faster** |
| ladybug | direct_cypher | lookup_miss | 20 | 0.331 | 0.383 | — | 0.335 | **-1.2% faster** | 0.381 | +0.7% acceptable |
| ladybug | qw_cypher | fanout | 20 | 5.355 | 5.417 | 1.25× | 5.312 | +0.8% acceptable | 5.355 | +1.2% acceptable |
| ladybug | qw_cypher | lookup | 20 | 1.768 | 1.836 | 1.69× | 1.761 | +0.4% acceptable | 1.830 | +0.3% acceptable |
| ladybug | qw_cypher | lookup_miss | 20 | 1.756 | 1.834 | 5.30× | 1.742 | +0.8% acceptable | 1.804 | +1.7% acceptable |
| ladybug | qw_gql | fanout | 20 | 5.706 | 5.772 | 1.33× | 5.557 | +2.7% acceptable | 5.632 | +2.5% acceptable |
| ladybug | qw_gql | lookup | 20 | 2.050 | 2.101 | 1.96× | 1.947 | +5.2% acceptable | 2.012 | +4.4% acceptable |
| ladybug | qw_gql | lookup_miss | 20 | 2.016 | 2.093 | 6.09× | 1.941 | +3.9% acceptable | 2.011 | +4.1% acceptable |
| relate | direct_cypher | fanout | 20 | 10.750 | 10.844 | — | 10.780 | **-0.3% faster** | 11.045 | **-1.8% faster** |
| relate | direct_cypher | lookup | 20 | 0.167 | 0.220 | — | 0.182 | **-8.0% faster** | 0.271 | **-18.9% faster** |
| relate | direct_cypher | lookup_miss | 20 | 0.247 | 0.314 | — | 0.265 | **-6.6% faster** | 0.366 | **-14.4% faster** |
| relate | qw_cypher | fanout | 20 | 11.295 | 11.533 | 1.05× | 11.355 | **-0.5% faster** | 11.609 | **-0.6% faster** |
| relate | qw_cypher | lookup | 20 | 1.809 | 2.547 | 10.82× | 1.833 | **-1.3% faster** | 2.207 | **+15.4% regression** |
| relate | qw_cypher | lookup_miss | 20 | 1.768 | 2.071 | 7.15× | 1.845 | **-4.2% faster** | 2.118 | **-2.2% faster** |
| relate | qw_gql | fanout | 20 | 11.638 | 11.804 | 1.08× | 11.524 | +1.0% acceptable | 11.719 | +0.7% acceptable |
| relate | qw_gql | lookup | 20 | 2.006 | 2.299 | 12.00× | 1.992 | +0.7% acceptable | 2.339 | **-1.7% faster** |
| relate | qw_gql | lookup_miss | 20 | 1.985 | 2.464 | 8.03× | 2.044 | **-2.9% faster** | 2.391 | +3.1% acceptable |

#### Hybrid SQL and graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 237.953 | 274.718 | — | 256.109 | **-7.1% faster** | 277.129 | **-0.9% faster** |
| ladybug | qw_pgq | graph_table_where | 20 | 6.111 | 6.872 | — | 6.099 | +0.2% acceptable | 6.954 | **-1.2% faster** |
| ladybug | qw_pgq | outer_where | 20 | 6.083 | 6.878 | — | 6.163 | **-1.3% faster** | 6.901 | **-0.3% faster** |
| ladybug | qw_pgq | table_watchlist | 20 | 13.859 | 14.960 | — | 14.024 | **-1.2% faster** | 14.956 | <+0.1% acceptable |
| ladybug | qw_pgq | values_watchlist | 20 | 13.377 | 13.837 | — | 13.348 | +0.2% acceptable | 14.785 | **-6.4% faster** |
| ladybug | qw_pgq | view_where | 20 | 6.972 | 7.696 | — | 7.112 | **-2.0% faster** | 7.745 | **-0.6% faster** |
| relate | qw_pgq | full_scan_aggregate | 20 | 5,016.783 | 5,065.155 | — | 4,927.406 | +1.8% acceptable | 5,008.521 | +1.1% acceptable |
| relate | qw_pgq | graph_table_where | 20 | 13.265 | 13.489 | — | 13.118 | +1.1% acceptable | 13.546 | **-0.4% faster** |
| relate | qw_pgq | outer_where | 20 | 13.332 | 13.763 | — | 13.362 | **-0.2% faster** | 13.564 | +1.5% acceptable |
| relate | qw_pgq | table_watchlist | 20 | 91.737 | 93.290 | — | 89.878 | +2.1% acceptable | 91.273 | +2.2% acceptable |
| relate | qw_pgq | values_watchlist | 20 | 90.482 | 91.955 | — | 89.202 | +1.4% acceptable | 90.117 | +2.0% acceptable |
| relate | qw_pgq | view_where | 20 | 14.179 | 14.651 | — | 14.059 | +0.9% acceptable | 14.598 | +0.4% acceptable |

