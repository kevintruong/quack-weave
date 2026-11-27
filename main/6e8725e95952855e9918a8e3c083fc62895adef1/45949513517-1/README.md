### Benchmark `6e8725e95952` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `54b2db6047ca` on the same runner. The two releases alternated order across measurement blocks.

Warm client latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**0 workloads with regressions · 18 with faster timings**

#### Standalone graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.259 | 4.322 | — | 4.226 | +0.8% acceptable | 4.257 | +1.5% acceptable |
| ladybug | direct_cypher | lookup | 20 | 1.002 | 1.042 | — | 0.988 | +1.4% acceptable | 1.017 | +2.4% acceptable |
| ladybug | direct_cypher | lookup_miss | 20 | 0.306 | 0.340 | — | 0.299 | +2.1% acceptable | 0.331 | +2.7% acceptable |
| ladybug | qw_cypher | fanout | 20 | 5.131 | 5.200 | 1.20× | 5.184 | **-1.0% faster** | 5.256 | **-1.1% faster** |
| ladybug | qw_cypher | lookup | 20 | 1.636 | 1.697 | 1.63× | 1.665 | **-1.8% faster** | 1.748 | **-2.9% faster** |
| ladybug | qw_cypher | lookup_miss | 20 | 1.596 | 1.658 | 5.22× | 1.616 | **-1.3% faster** | 1.704 | **-2.7% faster** |
| ladybug | qw_gql | fanout | 20 | 5.374 | 5.455 | 1.26× | 5.374 | **>-0.1% faster** | 5.469 | **-0.3% faster** |
| ladybug | qw_gql | lookup | 20 | 1.809 | 1.863 | 1.81× | 1.796 | +0.7% acceptable | 1.883 | **-1.0% faster** |
| ladybug | qw_gql | lookup_miss | 20 | 1.784 | 1.827 | 5.84× | 1.782 | +0.1% acceptable | 1.832 | **-0.3% faster** |
| relate | direct_cypher | fanout | 20 | 10.638 | 10.772 | — | 10.654 | **-0.1% faster** | 10.695 | +0.7% acceptable |
| relate | direct_cypher | lookup | 20 | 0.151 | 0.188 | — | 0.160 | **-5.9% faster** | 0.185 | +1.1% acceptable |
| relate | direct_cypher | lookup_miss | 20 | 0.218 | 0.242 | — | 0.211 | +3.0% acceptable | 0.251 | **-3.7% faster** |
| relate | qw_cypher | fanout | 20 | 10.998 | 11.388 | 1.03× | 10.860 | +1.3% acceptable | 11.142 | +2.2% acceptable |
| relate | qw_cypher | lookup | 20 | 1.643 | 1.797 | 10.91× | 1.584 | +3.7% acceptable | 1.690 | +6.3% acceptable |
| relate | qw_cypher | lookup_miss | 20 | 1.667 | 1.838 | 7.66× | 1.602 | +4.1% acceptable | 1.685 | +9.1% acceptable |
| relate | qw_gql | fanout | 20 | 11.130 | 11.464 | 1.05× | 11.199 | **-0.6% faster** | 11.601 | **-1.2% faster** |
| relate | qw_gql | lookup | 20 | 1.778 | 1.882 | 11.81× | 1.853 | **-4.1% faster** | 1.961 | **-4.0% faster** |
| relate | qw_gql | lookup_miss | 20 | 1.799 | 1.859 | 8.27× | 1.857 | **-3.1% faster** | 1.954 | **-4.9% faster** |

#### Hybrid SQL and graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 216.817 | 234.756 | — | 225.797 | **-4.0% faster** | 240.980 | **-2.6% faster** |
| ladybug | qw_pgq | graph_table_where | 20 | 5.841 | 6.643 | — | 5.837 | +0.1% acceptable | 6.730 | **-1.3% faster** |
| ladybug | qw_pgq | outer_where | 20 | 5.921 | 6.581 | — | 5.900 | +0.4% acceptable | 6.740 | **-2.4% faster** |
| ladybug | qw_pgq | table_watchlist | 20 | 13.366 | 14.856 | — | 13.661 | **-2.2% faster** | 14.211 | +4.5% acceptable |
| ladybug | qw_pgq | values_watchlist | 20 | 12.841 | 13.915 | — | 12.878 | **-0.3% faster** | 13.880 | +0.3% acceptable |
| ladybug | qw_pgq | view_where | 20 | 6.695 | 7.569 | — | 6.571 | +1.9% acceptable | 7.441 | +1.7% acceptable |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,987.159 | 5,066.883 | — | 4,939.857 | +1.0% acceptable | 5,020.301 | +0.9% acceptable |
| relate | qw_pgq | graph_table_where | 20 | 12.986 | 14.271 | — | 12.644 | +2.7% acceptable | 13.173 | +8.3% acceptable |
| relate | qw_pgq | outer_where | 20 | 12.923 | 13.490 | — | 12.783 | +1.1% acceptable | 13.102 | +3.0% acceptable |
| relate | qw_pgq | table_watchlist | 20 | 91.005 | 93.126 | — | 89.598 | +1.6% acceptable | 91.165 | +2.2% acceptable |
| relate | qw_pgq | values_watchlist | 20 | 89.712 | 93.346 | — | 88.518 | +1.3% acceptable | 89.706 | +4.1% acceptable |
| relate | qw_pgq | view_where | 20 | 13.464 | 13.996 | — | 13.562 | **-0.7% faster** | 13.848 | +1.1% acceptable |

