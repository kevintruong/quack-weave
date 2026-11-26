### Benchmark `d9e4a395038c` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `193c286db665` on the same runner. The two releases alternated order across measurement blocks.

Latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**1 workloads with regressions · 22 with faster timings**

- ladybug/direct_cypher/lookup_miss (p50 +10.3%, p95 +23.4%)

#### Standalone graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.336 | 4.569 | — | 4.356 | **-0.5% faster** | 4.483 | +1.9% acceptable |
| ladybug | direct_cypher | lookup | 20 | 1.069 | 1.253 | — | 1.031 | +3.7% acceptable | 1.148 | +9.2% acceptable |
| ladybug | direct_cypher | lookup_miss | 20 | 0.368 | 0.553 | — | 0.334 | **+10.3% regression** | 0.448 | **+23.4% regression** |
| ladybug | qw_cypher | fanout | 20 | 5.544 | 6.006 | 1.28× | 5.435 | +2.0% acceptable | 5.994 | +0.2% acceptable |
| ladybug | qw_cypher | lookup | 20 | 1.779 | 2.600 | 1.66× | 1.877 | **-5.2% faster** | 2.605 | **-0.2% faster** |
| ladybug | qw_cypher | lookup_miss | 20 | 1.899 | 2.567 | 5.16× | 1.772 | +7.2% acceptable | 2.629 | **-2.4% faster** |
| ladybug | qw_gql | fanout | 20 | 5.859 | 6.240 | 1.35× | 5.759 | +1.7% acceptable | 6.013 | +3.8% acceptable |
| ladybug | qw_gql | lookup | 20 | 2.112 | 2.737 | 1.98× | 2.065 | +2.3% acceptable | 2.600 | +5.3% acceptable |
| ladybug | qw_gql | lookup_miss | 20 | 2.130 | 2.586 | 5.78× | 2.028 | +5.0% acceptable | 2.515 | +2.8% acceptable |
| relate | direct_cypher | fanout | 20 | 10.849 | 11.178 | — | 10.919 | **-0.6% faster** | 11.059 | +1.1% acceptable |
| relate | direct_cypher | lookup | 20 | 0.191 | 0.336 | — | 0.187 | +2.2% acceptable | 0.344 | **-2.5% faster** |
| relate | direct_cypher | lookup_miss | 20 | 0.260 | 0.445 | — | 0.273 | **-4.8% faster** | 0.428 | +4.2% acceptable |
| relate | qw_cypher | fanout | 20 | 11.590 | 11.774 | 1.07× | 11.341 | +2.2% acceptable | 11.797 | **-0.2% faster** |
| relate | qw_cypher | lookup | 20 | 2.171 | 2.787 | 11.36× | 2.166 | +0.3% acceptable | 3.007 | **-7.3% faster** |
| relate | qw_cypher | lookup_miss | 20 | 2.207 | 2.770 | 8.50× | 2.158 | +2.3% acceptable | 2.724 | +1.7% acceptable |
| relate | qw_gql | fanout | 20 | 11.671 | 12.141 | 1.08× | 11.717 | **-0.4% faster** | 12.224 | **-0.7% faster** |
| relate | qw_gql | lookup | 20 | 2.314 | 3.038 | 12.11× | 2.513 | **-7.9% faster** | 3.139 | **-3.2% faster** |
| relate | qw_gql | lookup_miss | 20 | 2.420 | 2.998 | 9.32× | 2.542 | **-4.8% faster** | 3.275 | **-8.4% faster** |

#### Hybrid SQL and graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 284.288 | 320.625 | — | 292.688 | **-2.9% faster** | 298.070 | +7.6% acceptable |
| ladybug | qw_pgq | graph_table_where | 20 | 6.845 | 7.385 | — | 7.098 | **-3.6% faster** | 7.265 | +1.7% acceptable |
| ladybug | qw_pgq | outer_where | 20 | 6.963 | 7.439 | — | 7.057 | **-1.3% faster** | 7.402 | +0.5% acceptable |
| ladybug | qw_pgq | table_watchlist | 20 | 14.942 | 15.909 | — | 15.334 | **-2.6% faster** | 16.046 | **-0.9% faster** |
| ladybug | qw_pgq | values_watchlist | 20 | 14.514 | 15.593 | — | 14.463 | +0.4% acceptable | 15.617 | **-0.2% faster** |
| ladybug | qw_pgq | view_where | 20 | 7.797 | 8.417 | — | 7.994 | **-2.5% faster** | 8.347 | +0.8% acceptable |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,939.829 | 4,990.985 | — | 4,995.359 | **-1.1% faster** | 5,044.978 | **-1.1% faster** |
| relate | qw_pgq | graph_table_where | 20 | 13.567 | 19.324 | — | 13.742 | **-1.3% faster** | 18.352 | +5.3% acceptable |
| relate | qw_pgq | outer_where | 20 | 13.618 | 14.117 | — | 13.706 | **-0.6% faster** | 21.037 | **-32.9% faster** |
| relate | qw_pgq | table_watchlist | 20 | 92.763 | 100.088 | — | 92.730 | <+0.1% acceptable | 97.197 | +3.0% acceptable |
| relate | qw_pgq | values_watchlist | 20 | 91.451 | 92.532 | — | 90.910 | +0.6% acceptable | 97.016 | **-4.6% faster** |
| relate | qw_pgq | view_where | 20 | 14.481 | 14.910 | — | 14.618 | **-0.9% faster** | 15.013 | **-0.7% faster** |

