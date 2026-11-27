### Benchmark `29b024cfefc9` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `54b2db6047ca` on the same runner. The two releases alternated order across measurement blocks.

Warm client latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**2 workloads with regressions · 16 with faster timings**

- relate/qw_pgq/graph_table_where (p95 +17.2%)
- relate/qw_pgq/values_watchlist (p95 +13.3%)

#### Standalone graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.339 | 4.487 | — | 4.346 | **-0.2% faster** | 4.477 | +0.2% acceptable |
| ladybug | direct_cypher | lookup | 20 | 1.038 | 1.086 | — | 1.039 | **-0.1% faster** | 1.095 | **-0.8% faster** |
| ladybug | direct_cypher | lookup_miss | 20 | 0.336 | 0.377 | — | 0.334 | +0.7% acceptable | 0.379 | **-0.6% faster** |
| ladybug | qw_cypher | fanout | 20 | 5.457 | 5.607 | 1.26× | 5.383 | +1.4% acceptable | 5.539 | +1.2% acceptable |
| ladybug | qw_cypher | lookup | 20 | 1.888 | 1.980 | 1.82× | 1.805 | +4.6% acceptable | 1.885 | +5.0% acceptable |
| ladybug | qw_cypher | lookup_miss | 20 | 1.825 | 1.901 | 5.43× | 1.778 | +2.6% acceptable | 1.847 | +2.9% acceptable |
| ladybug | qw_gql | fanout | 20 | 5.772 | 5.867 | 1.33× | 5.703 | +1.2% acceptable | 5.831 | +0.6% acceptable |
| ladybug | qw_gql | lookup | 20 | 2.125 | 2.237 | 2.05× | 2.031 | +4.6% acceptable | 2.120 | +5.5% acceptable |
| ladybug | qw_gql | lookup_miss | 20 | 2.066 | 2.154 | 6.15× | 2.025 | +2.0% acceptable | 2.122 | +1.5% acceptable |
| relate | direct_cypher | fanout | 20 | 10.712 | 10.927 | — | 10.844 | **-1.2% faster** | 10.962 | **-0.3% faster** |
| relate | direct_cypher | lookup | 20 | 0.172 | 0.235 | — | 0.171 | +0.5% acceptable | 0.233 | +0.8% acceptable |
| relate | direct_cypher | lookup_miss | 20 | 0.255 | 0.299 | — | 0.253 | +1.0% acceptable | 0.319 | **-6.2% faster** |
| relate | qw_cypher | fanout | 20 | 11.316 | 11.569 | 1.06× | 11.361 | **-0.4% faster** | 11.534 | +0.3% acceptable |
| relate | qw_cypher | lookup | 20 | 1.937 | 2.192 | 11.28× | 1.884 | +2.8% acceptable | 2.074 | +5.7% acceptable |
| relate | qw_cypher | lookup_miss | 20 | 1.982 | 2.095 | 7.77× | 1.925 | +3.0% acceptable | 2.098 | **-0.1% faster** |
| relate | qw_gql | fanout | 20 | 11.578 | 11.709 | 1.08× | 11.545 | +0.3% acceptable | 11.813 | **-0.9% faster** |
| relate | qw_gql | lookup | 20 | 2.091 | 2.362 | 12.18× | 2.088 | +0.1% acceptable | 2.348 | +0.6% acceptable |
| relate | qw_gql | lookup_miss | 20 | 2.145 | 2.232 | 8.41× | 2.104 | +1.9% acceptable | 2.407 | **-7.3% faster** |

#### Hybrid SQL and graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 285.909 | 293.971 | — | 289.313 | **-1.2% faster** | 295.629 | **-0.6% faster** |
| ladybug | qw_pgq | graph_table_where | 20 | 6.424 | 7.060 | — | 6.466 | **-0.6% faster** | 7.001 | +0.8% acceptable |
| ladybug | qw_pgq | outer_where | 20 | 6.366 | 7.052 | — | 6.530 | **-2.5% faster** | 7.058 | **-0.1% faster** |
| ladybug | qw_pgq | table_watchlist | 20 | 14.445 | 15.205 | — | 14.580 | **-0.9% faster** | 15.346 | **-0.9% faster** |
| ladybug | qw_pgq | values_watchlist | 20 | 13.757 | 14.409 | — | 13.729 | +0.2% acceptable | 14.799 | **-2.6% faster** |
| ladybug | qw_pgq | view_where | 20 | 7.277 | 7.887 | — | 7.205 | +1.0% acceptable | 7.984 | **-1.2% faster** |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,938.929 | 4,975.509 | — | 4,944.369 | **-0.1% faster** | 5,020.531 | **-0.9% faster** |
| relate | qw_pgq | graph_table_where | 20 | 13.506 | 15.953 | — | 13.382 | +0.9% acceptable | 13.612 | **+17.2% regression** |
| relate | qw_pgq | outer_where | 20 | 13.530 | 14.087 | — | 13.340 | +1.4% acceptable | 13.640 | +3.3% acceptable |
| relate | qw_pgq | table_watchlist | 20 | 93.387 | 100.414 | — | 91.157 | +2.4% acceptable | 92.838 | +8.2% acceptable |
| relate | qw_pgq | values_watchlist | 20 | 92.123 | 102.958 | — | 89.895 | +2.5% acceptable | 90.859 | **+13.3% regression** |
| relate | qw_pgq | view_where | 20 | 14.301 | 14.570 | — | 14.126 | +1.2% acceptable | 14.374 | +1.4% acceptable |

