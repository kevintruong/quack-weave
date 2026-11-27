### Benchmark `fb346d7a59c8` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `3e28489e33e6` on the same runner. The two releases alternated order across measurement blocks.

#### Warm graph-engine execution

Each provider reports execution inside its engine. Diagnostics use the same query order and result checks as the release.

| Provider | Route | Workload | Engine samples | p50 (ms) | p95 (ms) | p50 change | p95 change | Other warm work p50 (ms) |
|---|---|---|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 2.460 | 2.486 | +0.3% acceptable | **-0.2% faster** | — |
| ladybug | direct_cypher | lookup | 20 | 0.053 | 0.070 | **+15.2% regression** | +2.9% acceptable | — |
| ladybug | direct_cypher | lookup_miss | 20 | 0.041 | 0.072 | +8.0% acceptable | **+41.2% regression** | — |
| ladybug | qw_cypher | fanout | 20 | 2.424 | 2.484 | — | — | 3.097 |
| ladybug | qw_cypher | lookup | 20 | 0.071 | 0.088 | — | — | 1.868 |
| ladybug | qw_cypher | lookup_miss | 20 | 0.054 | 0.077 | — | — | 1.858 |
| ladybug | qw_gql | fanout | 20 | 2.466 | 2.511 | — | — | 3.471 |
| ladybug | qw_gql | lookup | 20 | 0.072 | 0.090 | — | — | 2.150 |
| ladybug | qw_gql | lookup_miss | 20 | 0.063 | 0.077 | — | — | 2.123 |
| relate | direct_cypher | fanout | 20 | 8.931 | 8.982 | +0.3% acceptable | **-0.3% faster** | — |
| relate | direct_cypher | lookup | 20 | 0.042 | 0.088 | +2.5% acceptable | +1.6% acceptable | — |
| relate | direct_cypher | lookup_miss | 20 | 0.047 | 0.073 | +2.7% acceptable | +3.3% acceptable | — |
| relate | qw_cypher | fanout | 20 | 8.933 | 9.016 | — | — | 2.581 |
| relate | qw_cypher | lookup | 20 | 0.117 | 0.144 | — | — | 2.080 |
| relate | qw_cypher | lookup_miss | 20 | 0.115 | 0.130 | — | — | 2.229 |
| relate | qw_gql | fanout | 20 | 8.898 | 8.991 | — | — | 2.977 |
| relate | qw_gql | lookup | 20 | 0.120 | 0.146 | — | — | 2.415 |
| relate | qw_gql | lookup_miss | 20 | 0.123 | 0.153 | — | — | 2.593 |

Other warm work is elapsed time outside native execution on the same diagnostic call, including preparation and Arrow fetch. Hybrid SQL includes DuckDB relational execution and has its own client timings below.

#### One-time connection bootstrap

Each connection contributes one sample. Registration includes opening the provider graph through DuckDB.

| Provider | Route | Connections | p50 (ms) | p95 (ms) | Open p50 | Load p50 | Register p50 |
|---|---|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | 4 | 19.118 | 22.233 | 19.118 | — | — |
| ladybug | qw_cypher | 4 | 93.718 | 97.636 | 42.902 | 10.870 | 37.295 |
| ladybug | qw_gql | 4 | 91.810 | 94.963 | 42.313 | 10.731 | 36.079 |
| ladybug | qw_pgq | 4 | 93.580 | 96.009 | 42.967 | 11.083 | 36.961 |
| relate | direct_cypher | 4 | 17019.281 | 17630.441 | 17019.281 | — | — |
| relate | qw_cypher | 4 | 18207.657 | 19253.576 | 43.167 | 11.105 | 18150.864 |
| relate | qw_gql | 4 | 18367.406 | 18939.249 | 42.954 | 10.625 | 18310.176 |
| relate | qw_pgq | 4 | 18449.449 | 18747.307 | 42.935 | 10.792 | 18393.295 |

Warm client latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**3 workloads with regressions · 18 with faster timings**

- ladybug/direct_cypher/lookup (p95 +18.0%)
- ladybug/direct_cypher/lookup_miss (p95 +25.4%)
- relate/qw_pgq/view_where (p95 +44.6%)

#### Standalone graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.529 | 5.000 | — | 4.455 | +1.7% acceptable | 4.547 | <+10% acceptable |
| ladybug | direct_cypher | lookup | 20 | 1.163 | 1.560 | — | 1.128 | +3.1% acceptable | 1.321 | **+18.0% regression** |
| ladybug | direct_cypher | lookup_miss | 20 | 0.455 | 0.741 | — | 0.425 | +6.9% acceptable | 0.591 | **+25.4% regression** |
| ladybug | qw_cypher | fanout | 20 | 5.653 | 5.973 | 1.25× | 5.519 | +2.4% acceptable | 5.998 | **-0.4% faster** |
| ladybug | qw_cypher | lookup | 20 | 1.945 | 2.587 | 1.67× | 1.976 | **-1.6% faster** | 2.774 | **-6.7% faster** |
| ladybug | qw_cypher | lookup_miss | 20 | 2.002 | 2.731 | 4.40× | 2.018 | **-0.8% faster** | 2.736 | **-0.2% faster** |
| ladybug | qw_gql | fanout | 20 | 5.815 | 6.246 | 1.28× | 5.862 | **-0.8% faster** | 6.199 | +0.7% acceptable |
| ladybug | qw_gql | lookup | 20 | 2.257 | 2.815 | 1.94× | 2.345 | **-3.8% faster** | 3.027 | **-7.0% faster** |
| ladybug | qw_gql | lookup_miss | 20 | 2.304 | 3.074 | 5.07× | 2.324 | **-0.9% faster** | 2.950 | +4.2% acceptable |
| relate | direct_cypher | fanout | 20 | 10.958 | 11.204 | — | 11.014 | **-0.5% faster** | 11.269 | **-0.6% faster** |
| relate | direct_cypher | lookup | 20 | 0.189 | 0.361 | — | 0.201 | **-5.9% faster** | 0.351 | +2.8% acceptable |
| relate | direct_cypher | lookup_miss | 20 | 0.325 | 0.444 | — | 0.331 | **-1.9% faster** | 0.461 | **-3.6% faster** |
| relate | qw_cypher | fanout | 20 | 11.589 | 11.881 | 1.06× | 11.575 | +0.1% acceptable | 11.744 | +1.2% acceptable |
| relate | qw_cypher | lookup | 20 | 2.142 | 2.838 | 11.30× | 2.185 | **-2.0% faster** | 2.658 | +6.8% acceptable |
| relate | qw_cypher | lookup_miss | 20 | 2.459 | 2.820 | 7.57× | 2.299 | +7.0% acceptable | 2.771 | +1.8% acceptable |
| relate | qw_gql | fanout | 20 | 11.647 | 11.852 | 1.06× | 11.701 | **-0.5% faster** | 12.076 | **-1.9% faster** |
| relate | qw_gql | lookup | 20 | 2.363 | 2.956 | 12.47× | 2.387 | **-1.0% faster** | 3.047 | **-3.0% faster** |
| relate | qw_gql | lookup_miss | 20 | 2.569 | 2.874 | 7.91× | 2.632 | **-2.4% faster** | 2.896 | **-0.8% faster** |

#### Hybrid SQL and graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 296.453 | 308.018 | — | 298.965 | **-0.8% faster** | 312.907 | **-1.6% faster** |
| ladybug | qw_pgq | graph_table_where | 20 | 7.181 | 7.415 | — | 7.028 | +2.2% acceptable | 7.382 | +0.5% acceptable |
| ladybug | qw_pgq | outer_where | 20 | 7.176 | 7.533 | — | 7.018 | +2.3% acceptable | 7.425 | +1.5% acceptable |
| ladybug | qw_pgq | table_watchlist | 20 | 15.496 | 17.299 | — | 15.378 | +0.8% acceptable | 16.037 | +7.9% acceptable |
| ladybug | qw_pgq | values_watchlist | 20 | 14.221 | 15.129 | — | 14.360 | **-1.0% faster** | 15.311 | **-1.2% faster** |
| ladybug | qw_pgq | view_where | 20 | 8.079 | 8.524 | — | 7.867 | +2.7% acceptable | 8.385 | +1.7% acceptable |
| relate | qw_pgq | full_scan_aggregate | 20 | 5,036.449 | 5,101.519 | — | 4,945.530 | +1.8% acceptable | 5,017.570 | +1.7% acceptable |
| relate | qw_pgq | graph_table_where | 20 | 13.816 | 13.996 | — | 13.681 | +1.0% acceptable | 14.023 | **-0.2% faster** |
| relate | qw_pgq | outer_where | 20 | 13.780 | 14.028 | — | 13.720 | +0.4% acceptable | 14.175 | **-1.0% faster** |
| relate | qw_pgq | table_watchlist | 20 | 93.681 | 100.968 | — | 92.857 | +0.9% acceptable | 94.333 | +7.0% acceptable |
| relate | qw_pgq | values_watchlist | 20 | 92.361 | 97.832 | — | 90.838 | +1.7% acceptable | 99.167 | **-1.3% faster** |
| relate | qw_pgq | view_where | 20 | 14.691 | 22.025 | — | 14.563 | +0.9% acceptable | 15.233 | **+44.6% regression** |

