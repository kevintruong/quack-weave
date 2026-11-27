### Benchmark `aeea23ee61fc` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `54b2db6047ca` on the same runner. The two releases alternated order across measurement blocks.

Warm client latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**1 workloads with regressions · 16 with faster timings**

- relate/qw_pgq/graph_table_where (p95 +30.7%)

#### Standalone graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.212 | 4.273 | — | 4.222 | **-0.2% faster** | 4.276 | **-0.1% faster** |
| ladybug | direct_cypher | lookup | 20 | 0.999 | 1.027 | — | 0.990 | +0.9% acceptable | 1.008 | +1.8% acceptable |
| ladybug | direct_cypher | lookup_miss | 20 | 0.308 | 0.337 | — | 0.291 | +5.7% acceptable | 0.320 | +5.3% acceptable |
| ladybug | qw_cypher | fanout | 20 | 5.123 | 5.270 | 1.22× | 5.149 | **-0.5% faster** | 5.231 | +0.7% acceptable |
| ladybug | qw_cypher | lookup | 20 | 1.644 | 1.719 | 1.65× | 1.651 | **-0.4% faster** | 1.730 | **-0.6% faster** |
| ladybug | qw_cypher | lookup_miss | 20 | 1.598 | 1.663 | 5.19× | 1.657 | **-3.6% faster** | 1.708 | **-2.7% faster** |
| ladybug | qw_gql | fanout | 20 | 5.459 | 5.551 | 1.30× | 5.314 | +2.7% acceptable | 5.457 | +1.7% acceptable |
| ladybug | qw_gql | lookup | 20 | 1.876 | 1.965 | 1.88× | 1.762 | +6.4% acceptable | 1.875 | +4.8% acceptable |
| ladybug | qw_gql | lookup_miss | 20 | 1.882 | 1.955 | 6.11× | 1.734 | +8.5% acceptable | 1.834 | +6.5% acceptable |
| relate | direct_cypher | fanout | 20 | 10.571 | 10.670 | — | 10.643 | **-0.7% faster** | 10.750 | **-0.7% faster** |
| relate | direct_cypher | lookup | 20 | 0.156 | 0.188 | — | 0.158 | **-0.8% faster** | 0.191 | **-2.0% faster** |
| relate | direct_cypher | lookup_miss | 20 | 0.203 | 0.237 | — | 0.212 | **-4.3% faster** | 0.243 | **-2.7% faster** |
| relate | qw_cypher | fanout | 20 | 10.917 | 11.171 | 1.03× | 10.904 | +0.1% acceptable | 11.132 | +0.3% acceptable |
| relate | qw_cypher | lookup | 20 | 1.603 | 1.713 | 10.25× | 1.606 | **-0.2% faster** | 1.706 | +0.4% acceptable |
| relate | qw_cypher | lookup_miss | 20 | 1.606 | 1.674 | 7.90× | 1.584 | +1.4% acceptable | 1.707 | **-1.9% faster** |
| relate | qw_gql | fanout | 20 | 11.102 | 11.328 | 1.05× | 11.084 | +0.2% acceptable | 11.366 | **-0.3% faster** |
| relate | qw_gql | lookup | 20 | 1.773 | 1.806 | 11.34× | 1.741 | +1.8% acceptable | 1.810 | **-0.2% faster** |
| relate | qw_gql | lookup_miss | 20 | 1.782 | 1.837 | 8.77× | 1.737 | +2.6% acceptable | 1.838 | **-0.1% faster** |

#### Hybrid SQL and graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 204.373 | 211.303 | — | 221.454 | **-7.7% faster** | 242.348 | **-12.8% faster** |
| ladybug | qw_pgq | graph_table_where | 20 | 5.794 | 6.696 | — | 5.746 | +0.8% acceptable | 6.687 | +0.1% acceptable |
| ladybug | qw_pgq | outer_where | 20 | 5.845 | 6.719 | — | 5.802 | +0.7% acceptable | 6.597 | +1.9% acceptable |
| ladybug | qw_pgq | table_watchlist | 20 | 13.441 | 14.916 | — | 13.262 | +1.4% acceptable | 14.342 | +4.0% acceptable |
| ladybug | qw_pgq | values_watchlist | 20 | 12.700 | 13.807 | — | 12.832 | **-1.0% faster** | 13.416 | +2.9% acceptable |
| ladybug | qw_pgq | view_where | 20 | 6.538 | 7.501 | — | 6.517 | +0.3% acceptable | 7.363 | +1.9% acceptable |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,973.545 | 5,052.032 | — | 4,925.205 | +1.0% acceptable | 4,976.544 | +1.5% acceptable |
| relate | qw_pgq | graph_table_where | 20 | 12.713 | 17.277 | — | 12.538 | +1.4% acceptable | 13.221 | **+30.7% regression** |
| relate | qw_pgq | outer_where | 20 | 12.745 | 13.656 | — | 12.663 | +0.6% acceptable | 13.202 | +3.4% acceptable |
| relate | qw_pgq | table_watchlist | 20 | 90.040 | 91.206 | — | 89.420 | +0.7% acceptable | 94.855 | **-3.8% faster** |
| relate | qw_pgq | values_watchlist | 20 | 89.030 | 90.264 | — | 88.084 | +1.1% acceptable | 89.602 | +0.7% acceptable |
| relate | qw_pgq | view_where | 20 | 13.550 | 18.508 | — | 13.578 | **-0.2% faster** | 24.945 | **-25.8% faster** |


[Verified Hybrid Query smoke snapshot](hybrid_snapshot.json)
