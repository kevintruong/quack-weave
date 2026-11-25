# Latest main benchmark report

[Archived attempt and raw data](main/01a9f5abdbf95f1facba6c311ff23c0d521da214/45713999355-1/)

### Benchmark `01a9f5abdbf9` · baseline

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

First compatible baseline for this runner and protocol.

#### Standalone graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct |
|---|---|---|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.293 | 4.438 | — |
| ladybug | direct_cypher | lookup | 20 | 1.039 | 1.106 | — |
| ladybug | direct_cypher | lookup_miss | 20 | 0.330 | 0.430 | — |
| ladybug | qw_cypher | fanout | 20 | 5.409 | 5.708 | 1.26× |
| ladybug | qw_cypher | lookup | 20 | 1.893 | 2.128 | 1.82× |
| ladybug | qw_cypher | lookup_miss | 20 | 1.778 | 2.299 | 5.39× |
| ladybug | qw_gql | fanout | 20 | 5.644 | 5.847 | 1.31× |
| ladybug | qw_gql | lookup | 20 | 2.050 | 2.344 | 1.97× |
| ladybug | qw_gql | lookup_miss | 20 | 1.976 | 2.457 | 5.99× |
| relate | direct_cypher | fanout | 20 | 11.048 | 11.153 | — |
| relate | direct_cypher | lookup | 20 | 0.179 | 0.333 | — |
| relate | direct_cypher | lookup_miss | 20 | 0.342 | 0.421 | — |
| relate | qw_cypher | fanout | 20 | 11.422 | 11.561 | 1.03× |
| relate | qw_cypher | lookup | 20 | 2.163 | 2.642 | 12.11× |
| relate | qw_cypher | lookup_miss | 20 | 2.221 | 2.621 | 6.50× |
| relate | qw_gql | fanout | 20 | 11.638 | 16.826 | 1.05× |
| relate | qw_gql | lookup | 20 | 2.223 | 2.791 | 12.44× |
| relate | qw_gql | lookup_miss | 20 | 2.423 | 2.959 | 7.09× |

#### Hybrid SQL and graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct |
|---|---|---|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 281.817 | 304.710 | — |
| ladybug | qw_pgq | graph_table_where | 20 | 6.643 | 7.213 | — |
| ladybug | qw_pgq | outer_where | 20 | 6.906 | 7.204 | — |
| ladybug | qw_pgq | table_watchlist | 20 | 14.626 | 15.946 | — |
| ladybug | qw_pgq | values_watchlist | 20 | 14.056 | 14.914 | — |
| ladybug | qw_pgq | view_where | 20 | 7.605 | 8.062 | — |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,960.375 | 5,069.383 | — |
| relate | qw_pgq | graph_table_where | 20 | 13.407 | 13.667 | — |
| relate | qw_pgq | outer_where | 20 | 13.535 | 13.853 | — |
| relate | qw_pgq | table_watchlist | 20 | 92.204 | 93.099 | — |
| relate | qw_pgq | values_watchlist | 20 | 90.606 | 91.546 | — |
| relate | qw_pgq | view_where | 20 | 14.207 | 14.683 | — |
