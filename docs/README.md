# Quack Weave documentation

The guide shows one build for Ladybug, RelateDB, and Neo4j Aura. It covers provider setup, SQL/PGQ queries that use `FROM GRAPH_TABLE (... MATCH ... COLUMNS (...))`, and SQLLogic verification. [Guide source](index.html) · [Published documentation](https://kevintruong.github.io/quack-weave/docs/)

[index.html](index.html) is the page source. [evidence.json](evidence.json) records the SQLLogic runs and the Jev and Z3 checks behind the evidence index. To preview without the browser engines, serve this repository with `python3 -m http.server` and open `/docs/`. The Playground build publishes the guide alongside its interactive examples.

## Core and native architecture

The architecture notebook traces a graph query from DuckDB's native grammar and optimizer hooks through the core registry, provider session, and typed batch bridge. It includes the Rust boundary types, scan and registration lifecycles, ordered-limit eligibility, and shadow feedback. [Open the architecture notebook](core-native-architecture.ipynb).

## Performance benchmarks

Use the Hybrid Query guide to run the SQLLogic witness, choose a scaled workload, and compare two verified snapshots. The design notebook records the workload, oracle, and replay contracts. The tracker reference covers standalone experiments and the CI archive. [Hybrid Query guide](hybrid-test-bench-guide.md) · [Design notebook](hybrid-test-bench-design.ipynb) · [Tracker reference](../benchmarks/provider_comparison/tracker/README.md)

The [benchmark page](benchmarks.html) compares Ladybug and RelateDB on the archived full SF1 baseline, the SQLLogic-verified CM-LDBC adaptation, and two runs of the synthetic fanout experiment. Each view identifies its fixture, latency boundary, source revision, and artifact hashes. The page includes a download of the chart observations for the selected run.

Regenerate the chart data from existing tracker and notebook reports. The exporter recomputes the plotted percentiles from the warm samples before writing the public summary.

```sh
python3 benchmarks/provider_comparison/tracker/export_page.py \
  --micro path/to/verified-micro.json \
  --fanout path/to/first/timing.json path/to/repeat/timing.json
```

Jev 1.14.0 routed the chart's percentile order check to `data_integrity.value_range`. Z3 verified that p95 is at least p50 for all 70 plotted series across five bounded requests. The exported data passed the same checks with solve IDs `sol_2172f4fa5376482b` and `sol_f96704b2ce7e461f` for SF1, `sol_9548a8f417864fab` for CM-LDBC, and `sol_13c1736a7a8f4bae` and `sol_a125bcce606340b3` for fanout.
