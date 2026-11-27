### Benchmark `a1b659c38ba6` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `54b2db6047ca` on the same runner. The two releases alternated order across measurement blocks.

Warm client latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**0 workloads with regressions · 13 with faster timings**

#### Standalone graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.274 | 4.318 | — | 4.234 | +0.9% acceptable | 4.271 | +1.1% acceptable |
| ladybug | direct_cypher | lookup | 20 | 1.015 | 1.059 | — | 0.999 | +1.6% acceptable | 1.016 | +4.3% acceptable |
| ladybug | direct_cypher | lookup_miss | 20 | 0.311 | 0.352 | — | 0.305 | +2.1% acceptable | 0.362 | **-2.8% faster** |
| ladybug | qw_cypher | fanout | 20 | 5.196 | 5.289 | 1.22× | 5.161 | +0.7% acceptable | 5.200 | +1.7% acceptable |
| ladybug | qw_cypher | lookup | 20 | 1.665 | 1.733 | 1.64× | 1.647 | +1.1% acceptable | 1.692 | +2.4% acceptable |
| ladybug | qw_cypher | lookup_miss | 20 | 1.655 | 1.692 | 5.32× | 1.620 | +2.1% acceptable | 1.687 | +0.3% acceptable |
| ladybug | qw_gql | fanout | 20 | 5.411 | 5.514 | 1.27× | 5.409 | <+0.1% acceptable | 5.509 | +0.1% acceptable |
| ladybug | qw_gql | lookup | 20 | 1.845 | 1.922 | 1.82× | 1.832 | +0.7% acceptable | 1.917 | +0.3% acceptable |
| ladybug | qw_gql | lookup_miss | 20 | 1.828 | 1.905 | 5.87× | 1.798 | +1.7% acceptable | 1.882 | +1.2% acceptable |
| relate | direct_cypher | fanout | 20 | 10.623 | 10.762 | — | 10.567 | +0.5% acceptable | 10.793 | **-0.3% faster** |
| relate | direct_cypher | lookup | 20 | 0.164 | 0.202 | — | 0.159 | +3.2% acceptable | 0.186 | +9.0% acceptable |
| relate | direct_cypher | lookup_miss | 20 | 0.225 | 0.266 | — | 0.215 | +4.5% acceptable | 0.249 | +7.0% acceptable |
| relate | qw_cypher | fanout | 20 | 11.033 | 11.180 | 1.04× | 11.039 | **>-0.1% faster** | 11.203 | **-0.2% faster** |
| relate | qw_cypher | lookup | 20 | 1.652 | 1.753 | 10.04× | 1.639 | +0.8% acceptable | 1.722 | +1.8% acceptable |
| relate | qw_cypher | lookup_miss | 20 | 1.637 | 1.744 | 7.29× | 1.643 | **-0.4% faster** | 1.716 | +1.7% acceptable |
| relate | qw_gql | fanout | 20 | 11.278 | 11.418 | 1.06× | 11.304 | **-0.2% faster** | 11.467 | **-0.4% faster** |
| relate | qw_gql | lookup | 20 | 1.822 | 1.928 | 11.08× | 1.857 | **-1.9% faster** | 2.009 | **-4.1% faster** |
| relate | qw_gql | lookup_miss | 20 | 1.827 | 1.990 | 8.14× | 1.875 | **-2.5% faster** | 1.973 | +0.9% acceptable |

#### Hybrid SQL and graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 219.714 | 247.198 | — | 217.014 | +1.2% acceptable | 241.100 | +2.5% acceptable |
| ladybug | qw_pgq | graph_table_where | 20 | 5.872 | 6.705 | — | 5.940 | **-1.1% faster** | 6.670 | +0.5% acceptable |
| ladybug | qw_pgq | outer_where | 20 | 5.965 | 6.720 | — | 5.936 | +0.5% acceptable | 6.736 | **-0.2% faster** |
| ladybug | qw_pgq | table_watchlist | 20 | 13.681 | 14.796 | — | 13.584 | +0.7% acceptable | 14.242 | +3.9% acceptable |
| ladybug | qw_pgq | values_watchlist | 20 | 12.913 | 13.399 | — | 12.939 | **-0.2% faster** | 13.639 | **-1.8% faster** |
| ladybug | qw_pgq | view_where | 20 | 6.741 | 7.503 | — | 6.611 | +2.0% acceptable | 7.477 | +0.4% acceptable |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,993.841 | 5,045.193 | — | 4,916.542 | +1.6% acceptable | 4,995.475 | +1.0% acceptable |
| relate | qw_pgq | graph_table_where | 20 | 12.832 | 13.200 | — | 12.922 | **-0.7% faster** | 13.336 | **-1.0% faster** |
| relate | qw_pgq | outer_where | 20 | 12.784 | 13.239 | — | 12.990 | **-1.6% faster** | 13.475 | **-1.7% faster** |
| relate | qw_pgq | table_watchlist | 20 | 90.764 | 92.363 | — | 89.956 | +0.9% acceptable | 92.024 | +0.4% acceptable |
| relate | qw_pgq | values_watchlist | 20 | 89.618 | 90.671 | — | 88.545 | +1.2% acceptable | 90.089 | +0.6% acceptable |
| relate | qw_pgq | view_where | 20 | 13.619 | 14.034 | — | 13.721 | **-0.7% faster** | 14.359 | **-2.3% faster** |

