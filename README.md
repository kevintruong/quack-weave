# Latest main benchmark report

[Archived attempt and raw data](main/263fa4990631035d7964a7bb3302ac02b0f93365/45548771210-1/)

### Benchmark `263fa4990631` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `0f030fd0e927` on the same runner. The two releases alternated order across measurement blocks.

Latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**2 workloads with regressions · 18 with faster timings**

- relate/direct_cypher/lookup (p95 +15.1%)
- relate/direct_cypher/lookup_miss (p95 +15.1%)

#### Standalone graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.257 | 4.347 | — | 4.261 | **-0.1% faster** | 4.326 | +0.5% acceptable |
| ladybug | direct_cypher | lookup | 20 | 1.023 | 1.051 | — | 1.021 | +0.2% acceptable | 1.055 | **-0.4% faster** |
| ladybug | direct_cypher | lookup_miss | 20 | 0.326 | 0.354 | — | 0.317 | +2.8% acceptable | 0.349 | +1.4% acceptable |
| ladybug | qw_cypher | fanout | 20 | 5.326 | 5.438 | 1.25× | 5.283 | +0.8% acceptable | 5.335 | +1.9% acceptable |
| ladybug | qw_cypher | lookup | 20 | 1.735 | 1.852 | 1.70× | 1.781 | **-2.6% faster** | 1.804 | +2.7% acceptable |
| ladybug | qw_cypher | lookup_miss | 20 | 1.696 | 1.819 | 5.20× | 1.744 | **-2.8% faster** | 1.767 | +2.9% acceptable |
| ladybug | qw_gql | fanout | 20 | 5.594 | 5.758 | 1.31× | 10.265 | **-45.5% faster** | 10.470 | **-45.0% faster** |
| ladybug | qw_gql | lookup | 20 | 1.983 | 2.089 | 1.94× | 5.743 | **-65.5% faster** | 5.922 | **-64.7% faster** |
| ladybug | qw_gql | lookup_miss | 20 | 1.971 | 2.087 | 6.05× | 6.303 | **-68.7% faster** | 6.400 | **-67.4% faster** |
| relate | direct_cypher | fanout | 20 | 10.701 | 10.845 | — | 10.719 | **-0.2% faster** | 10.809 | +0.3% acceptable |
| relate | direct_cypher | lookup | 20 | 0.169 | 0.235 | — | 0.164 | +2.8% acceptable | 0.204 | **+15.1% regression** |
| relate | direct_cypher | lookup_miss | 20 | 0.228 | 0.325 | — | 0.232 | **-1.4% faster** | 0.283 | **+15.1% regression** |
| relate | qw_cypher | fanout | 20 | 11.307 | 11.600 | 1.06× | 11.251 | +0.5% acceptable | 11.411 | +1.7% acceptable |
| relate | qw_cypher | lookup | 20 | 1.885 | 2.123 | 11.16× | 1.805 | +4.5% acceptable | 1.962 | +8.2% acceptable |
| relate | qw_cypher | lookup_miss | 20 | 1.883 | 2.099 | 8.25× | 1.822 | +3.4% acceptable | 1.929 | +8.8% acceptable |
| relate | qw_gql | fanout | 20 | 11.424 | 11.672 | 1.07× | 16.313 | **-30.0% faster** | 16.447 | **-29.0% faster** |
| relate | qw_gql | lookup | 20 | 1.966 | 2.273 | 11.64× | 6.010 | **-67.3% faster** | 6.204 | **-63.4% faster** |
| relate | qw_gql | lookup_miss | 20 | 1.961 | 2.351 | 8.59× | 6.584 | **-70.2% faster** | 6.804 | **-65.5% faster** |

#### Hybrid SQL and graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 257.100 | 273.640 | — | 254.314 | +1.1% acceptable | 259.538 | +5.4% acceptable |
| ladybug | qw_pgq | graph_table_where | 20 | 6.111 | 6.879 | — | 6.020 | +1.5% acceptable | 6.801 | +1.1% acceptable |
| ladybug | qw_pgq | outer_where | 20 | 6.230 | 6.922 | — | 6.063 | +2.8% acceptable | 6.744 | +2.6% acceptable |
| ladybug | qw_pgq | table_watchlist | 20 | 13.890 | 14.757 | — | 13.899 | **-0.1% faster** | 14.541 | +1.5% acceptable |
| ladybug | qw_pgq | values_watchlist | 20 | 13.174 | 14.185 | — | 13.355 | **-1.4% faster** | 14.366 | **-1.3% faster** |
| ladybug | qw_pgq | view_where | 20 | 7.048 | 7.799 | — | 6.872 | +2.6% acceptable | 7.562 | +3.1% acceptable |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,950.467 | 4,991.118 | — | 4,914.606 | +0.7% acceptable | 4,971.382 | +0.4% acceptable |
| relate | qw_pgq | graph_table_where | 20 | 13.236 | 13.505 | — | 13.306 | **-0.5% faster** | 13.497 | +0.1% acceptable |
| relate | qw_pgq | outer_where | 20 | 13.350 | 13.562 | — | 13.415 | **-0.5% faster** | 13.568 | **>-0.1% faster** |
| relate | qw_pgq | table_watchlist | 20 | 91.061 | 92.247 | — | 90.853 | +0.2% acceptable | 91.485 | +0.8% acceptable |
| relate | qw_pgq | values_watchlist | 20 | 89.666 | 90.394 | — | 90.021 | **-0.4% faster** | 91.261 | **-0.9% faster** |
| relate | qw_pgq | view_where | 20 | 14.021 | 14.509 | — | 14.048 | **-0.2% faster** | 14.295 | +1.5% acceptable |
