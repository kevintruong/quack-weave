# Latest main benchmark report

[Archived attempt and raw data](main/7bdfb95c951801779130e57c426bb7b53a7c453e/45551464093-1/)

### Benchmark `7bdfb95c9518` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `263fa4990631` on the same runner. The two releases alternated order across measurement blocks.

Latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**1 workloads with regressions · 24 with faster timings**

- relate/direct_cypher/lookup (p95 +48.3%)

#### Standalone graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.259 | 4.368 | — | 4.284 | **-0.6% faster** | 4.451 | **-1.9% faster** |
| ladybug | direct_cypher | lookup | 20 | 1.023 | 1.109 | — | 1.014 | +0.9% acceptable | 1.208 | **-8.2% faster** |
| ladybug | direct_cypher | lookup_miss | 20 | 0.325 | 0.388 | — | 0.322 | +1.0% acceptable | 0.577 | **-32.7% faster** |
| ladybug | qw_cypher | fanout | 20 | 5.291 | 5.485 | 1.24× | 5.297 | **-0.1% faster** | 5.499 | **-0.3% faster** |
| ladybug | qw_cypher | lookup | 20 | 1.754 | 2.090 | 1.71× | 1.773 | **-1.1% faster** | 2.104 | **-0.6% faster** |
| ladybug | qw_cypher | lookup_miss | 20 | 1.769 | 1.891 | 5.43× | 1.736 | +1.9% acceptable | 2.334 | **-19.0% faster** |
| ladybug | qw_gql | fanout | 20 | 5.634 | 5.784 | 1.32× | 5.559 | +1.4% acceptable | 5.778 | +0.1% acceptable |
| ladybug | qw_gql | lookup | 20 | 1.996 | 2.069 | 1.95× | 1.938 | +3.0% acceptable | 2.378 | **-13.0% faster** |
| ladybug | qw_gql | lookup_miss | 20 | 1.977 | 2.110 | 6.07× | 1.931 | +2.4% acceptable | 2.361 | **-10.6% faster** |
| relate | direct_cypher | fanout | 20 | 10.757 | 11.230 | — | 10.713 | +0.4% acceptable | 10.879 | +3.2% acceptable |
| relate | direct_cypher | lookup | 20 | 0.170 | 0.322 | — | 0.164 | +4.0% acceptable | 0.217 | **+48.3% regression** |
| relate | direct_cypher | lookup_miss | 20 | 0.236 | 0.364 | — | 0.233 | +1.4% acceptable | 0.368 | **-1.2% faster** |
| relate | qw_cypher | fanout | 20 | 11.336 | 11.487 | 1.05× | 11.462 | **-1.1% faster** | 12.518 | **-8.2% faster** |
| relate | qw_cypher | lookup | 20 | 1.867 | 2.354 | 10.96× | 1.986 | **-6.0% faster** | 3.020 | **-22.1% faster** |
| relate | qw_cypher | lookup_miss | 20 | 1.825 | 2.423 | 7.72× | 1.975 | **-7.6% faster** | 3.345 | **-27.6% faster** |
| relate | qw_gql | fanout | 20 | 11.613 | 12.101 | 1.08× | 11.528 | +0.7% acceptable | 18.198 | **-33.5% faster** |
| relate | qw_gql | lookup | 20 | 2.098 | 2.503 | 12.31× | 2.080 | +0.9% acceptable | 2.604 | **-3.9% faster** |
| relate | qw_gql | lookup_miss | 20 | 2.136 | 2.686 | 9.04× | 2.134 | +0.1% acceptable | 4.492 | **-40.2% faster** |

#### Hybrid SQL and graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 255.413 | 280.247 | — | 263.586 | **-3.1% faster** | 275.313 | +1.8% acceptable |
| ladybug | qw_pgq | graph_table_where | 20 | 6.290 | 7.031 | — | 6.212 | +1.2% acceptable | 7.047 | **-0.2% faster** |
| ladybug | qw_pgq | outer_where | 20 | 6.136 | 6.966 | — | 6.279 | **-2.3% faster** | 6.824 | +2.1% acceptable |
| ladybug | qw_pgq | table_watchlist | 20 | 14.009 | 15.340 | — | 14.103 | **-0.7% faster** | 14.889 | +3.0% acceptable |
| ladybug | qw_pgq | values_watchlist | 20 | 13.569 | 14.616 | — | 13.123 | +3.4% acceptable | 14.839 | **-1.5% faster** |
| ladybug | qw_pgq | view_where | 20 | 7.279 | 7.973 | — | 6.924 | +5.1% acceptable | 7.821 | +1.9% acceptable |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,967.830 | 4,989.011 | — | 4,915.867 | +1.1% acceptable | 4,961.917 | +0.5% acceptable |
| relate | qw_pgq | graph_table_where | 20 | 13.455 | 13.747 | — | 13.417 | +0.3% acceptable | 13.764 | **-0.1% faster** |
| relate | qw_pgq | outer_where | 20 | 13.405 | 13.618 | — | 13.462 | **-0.4% faster** | 13.774 | **-1.1% faster** |
| relate | qw_pgq | table_watchlist | 20 | 91.644 | 93.827 | — | 90.803 | +0.9% acceptable | 91.814 | +2.2% acceptable |
| relate | qw_pgq | values_watchlist | 20 | 90.142 | 90.867 | — | 89.677 | +0.5% acceptable | 90.909 | **>-0.1% faster** |
| relate | qw_pgq | view_where | 20 | 14.016 | 14.572 | — | 14.158 | **-1.0% faster** | 14.626 | **-0.4% faster** |
