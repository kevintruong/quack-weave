# Latest main benchmark report

[Archived attempt and raw data](main/54b2db6047ca5dacf702382200298b894e33ca10/45798658494-1/)

### Benchmark `54b2db6047ca` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `01a9f5abdbf9` on the same runner. The two releases alternated order across measurement blocks.

Latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**3 workloads with regressions · 27 with faster timings**

- ladybug/qw_gql/fanout (p95 +11.5%)
- ladybug/qw_gql/lookup (p95 +13.8%)
- ladybug/qw_gql/lookup_miss (p95 +21.3%)

#### Standalone graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.322 | 4.410 | — | 4.318 | +0.1% acceptable | 4.364 | +1.1% acceptable |
| ladybug | direct_cypher | lookup | 20 | 1.038 | 1.168 | — | 1.040 | **-0.1% faster** | 1.105 | +5.8% acceptable |
| ladybug | direct_cypher | lookup_miss | 20 | 0.335 | 0.394 | — | 0.337 | **-0.4% faster** | 0.390 | +1.0% acceptable |
| ladybug | qw_cypher | fanout | 20 | 5.364 | 5.505 | 1.24× | 5.406 | **-0.8% faster** | 5.599 | **-1.7% faster** |
| ladybug | qw_cypher | lookup | 20 | 1.753 | 1.856 | 1.69× | 1.822 | **-3.8% faster** | 1.956 | **-5.1% faster** |
| ladybug | qw_cypher | lookup_miss | 20 | 1.725 | 1.878 | 5.15× | 1.795 | **-3.9% faster** | 2.052 | **-8.5% faster** |
| ladybug | qw_gql | fanout | 20 | 5.647 | 6.394 | 1.31× | 5.611 | +0.6% acceptable | 5.732 | **+11.5% regression** |
| ladybug | qw_gql | lookup | 20 | 1.984 | 2.511 | 1.91× | 2.009 | **-1.2% faster** | 2.207 | **+13.8% regression** |
| ladybug | qw_gql | lookup_miss | 20 | 1.970 | 2.540 | 5.88× | 1.978 | **-0.4% faster** | 2.094 | **+21.3% regression** |
| relate | direct_cypher | fanout | 20 | 10.974 | 11.066 | — | 10.961 | +0.1% acceptable | 11.245 | **-1.6% faster** |
| relate | direct_cypher | lookup | 20 | 0.186 | 0.312 | — | 0.184 | +1.4% acceptable | 0.295 | +5.8% acceptable |
| relate | direct_cypher | lookup_miss | 20 | 0.297 | 0.394 | — | 0.294 | +1.1% acceptable | 0.400 | **-1.4% faster** |
| relate | qw_cypher | fanout | 20 | 11.197 | 11.349 | 1.02× | 11.399 | **-1.8% faster** | 11.504 | **-1.3% faster** |
| relate | qw_cypher | lookup | 20 | 1.871 | 2.350 | 10.04× | 2.060 | **-9.2% faster** | 2.479 | **-5.2% faster** |
| relate | qw_cypher | lookup_miss | 20 | 1.863 | 2.231 | 6.28× | 2.129 | **-12.5% faster** | 2.562 | **-12.9% faster** |
| relate | qw_gql | fanout | 20 | 11.479 | 11.645 | 1.05× | 11.630 | **-1.3% faster** | 11.778 | **-1.1% faster** |
| relate | qw_gql | lookup | 20 | 2.135 | 2.659 | 11.46× | 2.299 | **-7.2% faster** | 2.838 | **-6.3% faster** |
| relate | qw_gql | lookup_miss | 20 | 2.189 | 2.540 | 7.37× | 2.483 | **-11.8% faster** | 2.830 | **-10.2% faster** |

#### Hybrid SQL and graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 280.054 | 285.465 | — | 280.215 | **-0.1% faster** | 284.839 | +0.2% acceptable |
| ladybug | qw_pgq | graph_table_where | 20 | 6.683 | 6.986 | — | 6.526 | +2.4% acceptable | 7.038 | **-0.7% faster** |
| ladybug | qw_pgq | outer_where | 20 | 6.625 | 7.032 | — | 6.648 | **-0.3% faster** | 7.083 | **-0.7% faster** |
| ladybug | qw_pgq | table_watchlist | 20 | 14.628 | 15.081 | — | 14.601 | +0.2% acceptable | 15.651 | **-3.6% faster** |
| ladybug | qw_pgq | values_watchlist | 20 | 14.177 | 14.769 | — | 14.036 | +1.0% acceptable | 15.116 | **-2.3% faster** |
| ladybug | qw_pgq | view_where | 20 | 7.531 | 7.905 | — | 7.610 | **-1.0% faster** | 7.929 | **-0.3% faster** |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,962.812 | 5,045.405 | — | 4,964.996 | **>-0.1% faster** | 5,017.079 | +0.6% acceptable |
| relate | qw_pgq | graph_table_where | 20 | 13.463 | 13.734 | — | 13.672 | **-1.5% faster** | 23.684 | **-42.0% faster** |
| relate | qw_pgq | outer_where | 20 | 13.477 | 13.753 | — | 13.749 | **-2.0% faster** | 14.252 | **-3.5% faster** |
| relate | qw_pgq | table_watchlist | 20 | 92.977 | 95.979 | — | 92.593 | +0.4% acceptable | 98.727 | **-2.8% faster** |
| relate | qw_pgq | values_watchlist | 20 | 91.058 | 92.582 | — | 90.824 | +0.3% acceptable | 93.614 | **-1.1% faster** |
| relate | qw_pgq | view_where | 20 | 14.254 | 14.465 | — | 14.557 | **-2.1% faster** | 14.996 | **-3.5% faster** |
