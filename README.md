# Latest main benchmark report

[Archived attempt and raw data](main/4730ec4c7cbf96a5f7099b57bf5fdc672a822e13/45951210199-1/)

### Benchmark `4730ec4c7cbf` · passed

github-hosted/ubuntu-24.04-arm/arm64 · protocol 2 · 3,809,607 edges · 30 series · 600 warm samples.

Compared with main commit `54b2db6047ca` on the same runner. The two releases alternated order across measurement blocks.

#### Warm graph-engine execution

Each provider reports execution inside its engine. Diagnostics use the same query order and result checks as the release.

| Provider | Route | Workload | Engine samples | p50 (ms) | p95 (ms) | p50 change | p95 change | Other warm work p50 (ms) |
|---|---|---|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 2.426 | 2.459 | +0.2% acceptable | **-1.1% faster** | — |
| ladybug | direct_cypher | lookup | 20 | 0.042 | 0.082 | +2.4% acceptable | **+13.9% regression** | — |
| ladybug | direct_cypher | lookup_miss | 20 | 0.034 | 0.064 | 0.0% unchanged | **+45.5% regression** | — |
| ladybug | qw_cypher | fanout | 20 | 2.412 | 2.432 | — | — | 2.986 |
| ladybug | qw_cypher | lookup | 20 | 0.053 | 0.064 | — | — | 1.748 |
| ladybug | qw_cypher | lookup_miss | 20 | 0.043 | 0.058 | — | — | 1.744 |
| ladybug | qw_gql | fanout | 20 | 2.442 | 2.481 | — | — | 3.307 |
| ladybug | qw_gql | lookup | 20 | 0.060 | 0.088 | — | — | 1.988 |
| ladybug | qw_gql | lookup_miss | 20 | 0.048 | 0.074 | — | — | 2.014 |
| relate | direct_cypher | fanout | 20 | 8.866 | 8.922 | +0.8% acceptable | **-0.8% faster** | — |
| relate | direct_cypher | lookup | 20 | 0.035 | 0.068 | **+10.5% regression** | +2.9% acceptable | — |
| relate | direct_cypher | lookup_miss | 20 | 0.041 | 0.059 | +8.6% acceptable | +1.6% acceptable | — |
| relate | qw_cypher | fanout | 20 | 8.905 | 8.980 | — | — | 2.346 |
| relate | qw_cypher | lookup | 20 | 0.108 | 0.133 | — | — | 1.885 |
| relate | qw_cypher | lookup_miss | 20 | 0.099 | 0.126 | — | — | 1.988 |
| relate | qw_gql | fanout | 20 | 8.860 | 9.007 | — | — | 2.512 |
| relate | qw_gql | lookup | 20 | 0.100 | 0.146 | — | — | 2.031 |
| relate | qw_gql | lookup_miss | 20 | 0.091 | 0.118 | — | — | 2.035 |

Other warm work is elapsed time outside native execution on the same diagnostic call, including preparation and Arrow fetch. Hybrid SQL includes DuckDB relational execution and has its own client timings below.

#### One-time connection bootstrap

Each connection contributes one sample. Registration includes opening the provider graph through DuckDB.

| Provider | Route | Connections | p50 (ms) | p95 (ms) | Open p50 | Load p50 | Register p50 |
|---|---|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | 4 | 18.116 | 19.690 | 18.116 | — | — |
| ladybug | qw_cypher | 4 | 89.349 | 89.833 | 41.302 | 10.351 | 35.263 |
| ladybug | qw_gql | 4 | 89.792 | 92.935 | 41.670 | 10.430 | 35.220 |
| ladybug | qw_pgq | 4 | 89.189 | 92.376 | 41.466 | 10.444 | 34.836 |
| relate | direct_cypher | 4 | 15744.219 | 16115.951 | 15744.219 | — | — |
| relate | qw_cypher | 4 | 17386.016 | 17926.948 | 41.127 | 10.505 | 17331.119 |
| relate | qw_gql | 4 | 17366.025 | 17900.397 | 40.970 | 10.333 | 17313.060 |
| relate | qw_pgq | 4 | 17446.818 | 17664.283 | 41.365 | 10.688 | 17392.386 |

Warm client latency is advisory. A rise of 10% or more in either p50 or p95 warrants review. Negative changes mean faster queries.

**4 workloads with regressions · 13 with faster timings**

- ladybug/qw_gql/lookup_miss (p95 +15.3%)
- relate/qw_cypher/lookup (p50 +12.1%, p95 +11.8%)
- relate/qw_cypher/lookup_miss (p50 +13.0%, p95 +16.5%)
- relate/qw_gql/lookup_miss (p95 +26.0%)

#### Standalone graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | direct_cypher | fanout | 20 | 4.336 | 4.426 | — | 4.343 | **-0.1% faster** | 4.426 | <+0.1% acceptable |
| ladybug | direct_cypher | lookup | 20 | 1.045 | 1.106 | — | 1.053 | **-0.7% faster** | 1.145 | **-3.4% faster** |
| ladybug | direct_cypher | lookup_miss | 20 | 0.356 | 0.400 | — | 0.345 | +3.2% acceptable | 0.451 | **-11.2% faster** |
| ladybug | qw_cypher | fanout | 20 | 5.251 | 5.379 | 1.21× | 5.323 | **-1.4% faster** | 5.457 | **-1.4% faster** |
| ladybug | qw_cypher | lookup | 20 | 1.713 | 1.885 | 1.64× | 1.779 | **-3.7% faster** | 1.934 | **-2.6% faster** |
| ladybug | qw_cypher | lookup_miss | 20 | 1.688 | 1.852 | 4.74× | 1.727 | **-2.3% faster** | 1.961 | **-5.5% faster** |
| ladybug | qw_gql | fanout | 20 | 5.668 | 5.796 | 1.31× | 5.669 | **>-0.1% faster** | 5.831 | **-0.6% faster** |
| ladybug | qw_gql | lookup | 20 | 2.029 | 2.342 | 1.94× | 2.025 | +0.2% acceptable | 2.209 | +6.0% acceptable |
| ladybug | qw_gql | lookup_miss | 20 | 1.983 | 2.520 | 5.57× | 1.975 | +0.4% acceptable | 2.185 | **+15.3% regression** |
| relate | direct_cypher | fanout | 20 | 10.818 | 10.951 | — | 10.886 | **-0.6% faster** | 11.140 | **-1.7% faster** |
| relate | direct_cypher | lookup | 20 | 0.178 | 0.289 | — | 0.170 | +4.5% acceptable | 0.303 | **-4.5% faster** |
| relate | direct_cypher | lookup_miss | 20 | 0.283 | 0.387 | — | 0.289 | **-1.9% faster** | 0.415 | **-6.8% faster** |
| relate | qw_cypher | fanout | 20 | 11.333 | 11.686 | 1.05× | 11.144 | +1.7% acceptable | 11.286 | +3.5% acceptable |
| relate | qw_cypher | lookup | 20 | 1.975 | 2.477 | 11.10× | 1.762 | **+12.1% regression** | 2.215 | **+11.8% regression** |
| relate | qw_cypher | lookup_miss | 20 | 2.030 | 2.473 | 7.16× | 1.797 | **+13.0% regression** | 2.123 | **+16.5% regression** |
| relate | qw_gql | fanout | 20 | 11.407 | 11.756 | 1.05× | 11.428 | **-0.2% faster** | 11.690 | +0.6% acceptable |
| relate | qw_gql | lookup | 20 | 2.144 | 2.670 | 12.05× | 2.116 | +1.3% acceptable | 2.481 | +7.6% acceptable |
| relate | qw_gql | lookup_miss | 20 | 2.240 | 3.312 | 7.90× | 2.127 | +5.3% acceptable | 2.629 | **+26.0% regression** |

#### Hybrid SQL and graph queries · warm client latency through fetch

| Provider | Route | Workload | Samples | p50 (ms) | p95 (ms) | p50 / direct | Baseline p50 (ms) | p50 change | Baseline p95 (ms) | p95 change |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ladybug | qw_pgq | full_scan_aggregate | 20 | 280.559 | 285.736 | — | 279.872 | +0.2% acceptable | 283.500 | +0.8% acceptable |
| ladybug | qw_pgq | graph_table_where | 20 | 6.774 | 7.101 | — | 6.753 | +0.3% acceptable | 7.053 | +0.7% acceptable |
| ladybug | qw_pgq | outer_where | 20 | 6.731 | 7.060 | — | 6.678 | +0.8% acceptable | 6.995 | +0.9% acceptable |
| ladybug | qw_pgq | table_watchlist | 20 | 14.800 | 15.424 | — | 14.870 | **-0.5% faster** | 16.077 | **-4.1% faster** |
| ladybug | qw_pgq | values_watchlist | 20 | 13.869 | 14.958 | — | 14.073 | **-1.5% faster** | 15.305 | **-2.3% faster** |
| ladybug | qw_pgq | view_where | 20 | 7.566 | 8.060 | — | 7.507 | +0.8% acceptable | 7.919 | +1.8% acceptable |
| relate | qw_pgq | full_scan_aggregate | 20 | 5,001.766 | 5,142.839 | — | 4,961.124 | +0.8% acceptable | 5,020.710 | +2.4% acceptable |
| relate | qw_pgq | graph_table_where | 20 | 13.575 | 13.820 | — | 13.479 | +0.7% acceptable | 13.652 | +1.2% acceptable |
| relate | qw_pgq | outer_where | 20 | 13.647 | 14.017 | — | 13.299 | +2.6% acceptable | 13.567 | +3.3% acceptable |
| relate | qw_pgq | table_watchlist | 20 | 93.281 | 94.364 | — | 91.886 | +1.5% acceptable | 93.794 | +0.6% acceptable |
| relate | qw_pgq | values_watchlist | 20 | 91.874 | 93.040 | — | 90.016 | +2.1% acceptable | 91.330 | +1.9% acceptable |
| relate | qw_pgq | view_where | 20 | 14.503 | 14.780 | — | 14.280 | +1.6% acceptable | 14.611 | +1.2% acceptable |


[Verified Hybrid Query smoke snapshot](main/4730ec4c7cbf96a5f7099b57bf5fdc672a822e13/45951210199-1/hybrid_snapshot.json)
