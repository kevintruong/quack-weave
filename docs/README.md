# Quack Weave documentation

The guide shows one build for Ladybug, RelateDB, and Neo4j Aura. It covers provider setup, SQL/PGQ queries that use `FROM GRAPH_TABLE (... MATCH ... COLUMNS (...))`, and SQLLogic verification. [Guide source](index.html) · [Published documentation](https://kevintruong.github.io/quack-weave/docs/)

[index.html](index.html) is the page source. [evidence.json](evidence.json) records the SQLLogic runs and the Jev and Z3 checks behind the evidence index. To preview without the browser engines, serve this repository with `python3 -m http.server` and open `/docs/`. The Playground build publishes the guide alongside its interactive examples.

## Core and native architecture

The architecture notebook traces a graph query from DuckDB's native grammar and optimizer hooks through the core registry, provider session, and typed batch bridge. It includes the Rust boundary types, scan and registration lifecycles, ordered-limit eligibility, and shadow feedback. [Open the architecture notebook](core-native-architecture.ipynb).
