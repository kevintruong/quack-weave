# Latest main benchmark report

[Archived attempt and raw data](main/193c286db665cc72b4da68978fc3a61b50d9b85e/45634091677-1/)

### Benchmark `193c286db665` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `0183c0c31cf0` on the same runner. The two releases alternated order across measurement blocks.

Latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**2 workloads with regressions · 24 with faster timings**

- ladybug/qw_gql/lookup (p95 +11.5%)
- ladybug/qw_gql/lookup_miss (p95 +20.4%)

#### Standalone graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.294 | 4.401 | — | 4.323 | **-0.7% faster** | 4.448 | **-1.0% faster** |
| ladybug | direct_cypher | lookup | 20 | 1.031 | 1.085 | — | 1.044 | **-1.2% faster** | 1.103 | **-1.6% faster** |
| ladybug | direct_cypher | lookup_miss | 20 | 0.329 | 0.428 | — | 0.351 | **-6.2% faster** | 0.405 | +5.7% acceptable |
| ladybug | qw_cypher | fanout | 20 | 5.359 | 5.627 | 1.25× | 5.436 | **-1.4% faster** | 5.643 | **-0.3% faster** |
| ladybug | qw_cypher | lookup | 20 | 1.783 | 2.064 | 1.73× | 1.893 | **-5.8% faster** | 2.124 | **-2.8% faster** |
| ladybug | qw_cypher | lookup_miss | 20 | 1.759 | 2.265 | 5.34× | 1.859 | **-5.4% faster** | 2.223 | +1.9% acceptable |
| ladybug | qw_gql | fanout | 20 | 5.645 | 6.014 | 1.31× | 5.587 | +1.0% acceptable | 5.731 | +4.9% acceptable |
| ladybug | qw_gql | lookup | 20 | 2.024 | 2.443 | 1.96× | 1.944 | +4.1% acceptable | 2.192 | **+11.5% regression** |
| ladybug | qw_gql | lookup_miss | 20 | 2.015 | 2.585 | 6.12× | 1.953 | +3.2% acceptable | 2.148 | **+20.4% regression** |
| relate | direct_cypher | fanout | 20 | 10.859 | 11.265 | — | 10.958 | **-0.9% faster** | 11.194 | +0.6% acceptable |
| relate | direct_cypher | lookup | 20 | 0.169 | 0.363 | — | 0.190 | **-11.2% faster** | 0.333 | +8.8% acceptable |
| relate | direct_cypher | lookup_miss | 20 | 0.277 | 0.448 | — | 0.276 | +0.4% acceptable | 0.436 | +2.8% acceptable |
| relate | qw_cypher | fanout | 20 | 11.391 | 11.817 | 1.05× | 11.546 | **-1.3% faster** | 19.415 | **-39.1% faster** |
| relate | qw_cypher | lookup | 20 | 2.030 | 2.708 | 12.00× | 2.176 | **-6.7% faster** | 2.869 | **-5.6% faster** |
| relate | qw_cypher | lookup_miss | 20 | 2.043 | 2.650 | 7.38× | 2.272 | **-10.1% faster** | 2.667 | **-0.7% faster** |
| relate | qw_gql | fanout | 20 | 11.532 | 11.758 | 1.06× | 11.429 | +0.9% acceptable | 11.719 | +0.3% acceptable |
| relate | qw_gql | lookup | 20 | 2.030 | 2.463 | 12.00× | 2.043 | **-0.7% faster** | 2.624 | **-6.1% faster** |
| relate | qw_gql | lookup_miss | 20 | 2.071 | 2.539 | 7.48× | 2.087 | **-0.7% faster** | 2.594 | **-2.1% faster** |

#### Hybrid SQL and graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 278.092 | 291.432 | — | 284.978 | **-2.4% faster** | 295.755 | **-1.5% faster** |
| ladybug | qw_pgq | graph_table_where | 20 | 6.809 | 7.150 | — | 6.636 | +2.6% acceptable | 7.154 | **-0.1% faster** |
| ladybug | qw_pgq | outer_where | 20 | 6.561 | 7.197 | — | 6.826 | **-3.9% faster** | 7.155 | +0.6% acceptable |
| ladybug | qw_pgq | table_watchlist | 20 | 14.836 | 15.666 | — | 14.751 | +0.6% acceptable | 15.842 | **-1.1% faster** |
| ladybug | qw_pgq | values_watchlist | 20 | 13.925 | 15.304 | — | 14.369 | **-3.1% faster** | 15.120 | +1.2% acceptable |
| ladybug | qw_pgq | view_where | 20 | 7.566 | 8.000 | — | 7.559 | +0.1% acceptable | 8.130 | **-1.6% faster** |
| relate | qw_pgq | full_scan_aggregate | 20 | 5,013.836 | 5,081.709 | — | 4,962.363 | +1.0% acceptable | 5,037.011 | +0.9% acceptable |
| relate | qw_pgq | graph_table_where | 20 | 13.415 | 13.736 | — | 13.615 | **-1.5% faster** | 21.084 | **-34.9% faster** |
| relate | qw_pgq | outer_where | 20 | 13.588 | 14.044 | — | 13.559 | +0.2% acceptable | 15.744 | **-10.8% faster** |
| relate | qw_pgq | table_watchlist | 20 | 91.995 | 94.994 | — | 92.013 | **>-0.1% faster** | 93.307 | +1.8% acceptable |
| relate | qw_pgq | values_watchlist | 20 | 90.502 | 91.653 | — | 90.610 | **-0.1% faster** | 97.859 | **-6.3% faster** |
| relate | qw_pgq | view_where | 20 | 14.320 | 14.686 | — | 14.395 | **-0.5% faster** | 19.829 | **-25.9% faster** |
