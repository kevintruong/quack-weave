### Benchmark `0943fb9a5e16` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `01a9f5abdbf9` on the same runner. The two releases alternated order across measurement blocks.

Latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**3 workloads with regressions · 20 with faster timings**

- relate/qw_cypher/lookup_miss (p95 +10.9%)
- relate/qw_gql/fanout (p95 +35.2%)
- relate/qw_gql/lookup_miss (p95 +265.2%)

#### Standalone graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.277 | 4.341 | — | 4.230 | +1.1% acceptable | 4.352 | **-0.3% faster** |
| ladybug | direct_cypher | lookup | 20 | 1.024 | 1.065 | — | 1.016 | +0.8% acceptable | 1.043 | +2.1% acceptable |
| ladybug | direct_cypher | lookup_miss | 20 | 0.324 | 0.362 | — | 0.323 | +0.2% acceptable | 0.353 | +2.6% acceptable |
| ladybug | qw_cypher | fanout | 20 | 5.270 | 5.375 | 1.23× | 5.203 | +1.3% acceptable | 5.367 | +0.1% acceptable |
| ladybug | qw_cypher | lookup | 20 | 1.680 | 1.743 | 1.64× | 1.718 | **-2.2% faster** | 1.823 | **-4.4% faster** |
| ladybug | qw_cypher | lookup_miss | 20 | 1.670 | 1.721 | 5.16× | 1.661 | +0.6% acceptable | 1.809 | **-4.9% faster** |
| ladybug | qw_gql | fanout | 20 | 5.502 | 5.589 | 1.29× | 5.549 | **-0.9% faster** | 5.665 | **-1.3% faster** |
| ladybug | qw_gql | lookup | 20 | 1.849 | 1.896 | 1.81× | 1.946 | **-5.0% faster** | 2.061 | **-8.0% faster** |
| ladybug | qw_gql | lookup_miss | 20 | 1.833 | 1.889 | 5.66× | 1.934 | **-5.2% faster** | 2.007 | **-5.9% faster** |
| relate | direct_cypher | fanout | 20 | 10.687 | 10.851 | — | 10.704 | **-0.2% faster** | 10.805 | +0.4% acceptable |
| relate | direct_cypher | lookup | 20 | 0.162 | 0.219 | — | 0.164 | **-1.2% faster** | 0.225 | **-2.5% faster** |
| relate | direct_cypher | lookup_miss | 20 | 0.235 | 0.296 | — | 0.226 | +3.9% acceptable | 0.303 | **-2.2% faster** |
| relate | qw_cypher | fanout | 20 | 11.034 | 11.368 | 1.03× | 11.205 | **-1.5% faster** | 11.327 | +0.4% acceptable |
| relate | qw_cypher | lookup | 20 | 1.859 | 2.081 | 11.50× | 1.772 | +4.9% acceptable | 2.073 | +0.4% acceptable |
| relate | qw_cypher | lookup_miss | 20 | 1.842 | 2.179 | 7.84× | 1.815 | +1.5% acceptable | 1.965 | **+10.9% regression** |
| relate | qw_gql | fanout | 20 | 11.169 | 15.943 | 1.05× | 11.276 | **-0.9% faster** | 11.796 | **+35.2% regression** |
| relate | qw_gql | lookup | 20 | 1.867 | 2.066 | 11.54× | 2.030 | **-8.0% faster** | 2.204 | **-6.3% faster** |
| relate | qw_gql | lookup_miss | 20 | 1.848 | 8.145 | 7.87× | 2.012 | **-8.2% faster** | 2.230 | **+265.2% regression** |

#### Hybrid SQL and graph queries

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 262.213 | 272.382 | — | 260.168 | +0.8% acceptable | 274.333 | **-0.7% faster** |
| ladybug | qw_pgq | graph_table_where | 20 | 6.371 | 6.933 | — | 6.158 | +3.5% acceptable | 6.769 | +2.4% acceptable |
| ladybug | qw_pgq | outer_where | 20 | 6.408 | 6.927 | — | 6.238 | +2.7% acceptable | 6.782 | +2.1% acceptable |
| ladybug | qw_pgq | table_watchlist | 20 | 14.114 | 15.060 | — | 14.282 | **-1.2% faster** | 14.599 | +3.2% acceptable |
| ladybug | qw_pgq | values_watchlist | 20 | 13.274 | 14.260 | — | 13.528 | **-1.9% faster** | 14.692 | **-2.9% faster** |
| ladybug | qw_pgq | view_where | 20 | 7.132 | 7.697 | — | 6.894 | +3.5% acceptable | 7.681 | +0.2% acceptable |
| relate | qw_pgq | full_scan_aggregate | 20 | 4,960.954 | 4,992.774 | — | 4,922.540 | +0.8% acceptable | 5,030.931 | **-0.8% faster** |
| relate | qw_pgq | graph_table_where | 20 | 13.155 | 13.595 | — | 13.288 | **-1.0% faster** | 13.569 | +0.2% acceptable |
| relate | qw_pgq | outer_where | 20 | 13.194 | 13.507 | — | 13.279 | **-0.6% faster** | 13.649 | **-1.0% faster** |
| relate | qw_pgq | table_watchlist | 20 | 91.608 | 93.011 | — | 91.027 | +0.6% acceptable | 91.800 | +1.3% acceptable |
| relate | qw_pgq | values_watchlist | 20 | 90.486 | 91.511 | — | 89.886 | +0.7% acceptable | 91.048 | +0.5% acceptable |
| relate | qw_pgq | view_where | 20 | 13.915 | 14.319 | — | 14.013 | **-0.7% faster** | 14.283 | +0.3% acceptable |

