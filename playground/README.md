# Quack Weave Playground

The playground runs SQL in DuckDB Wasm and Cypher in Ladybug Wasm. PaperTrail is a synthetic citation dataset bundled as a Cypher seed and a Parquet file. At startup, Ladybug builds a database in its own filesystem and reopens it read-only. DuckDB loads `papers` from Parquet.

The guided hybrid example uses a SQL/PGQ-style `GRAPH_TABLE` join. The browser bridge supports `GRAPH_TABLE (kg MATCH … [WHERE …] COLUMNS (…))`: Ladybug executes the graph pattern, predicates, and projections. Use plain ASCII column names and `AS` where needed. The bridge infers `BOOLEAN`, `BIGINT`, `DOUBLE`, and `VARCHAR` from Ladybug's result metadata and passes the projected rows to DuckDB via typed Arrow IPC. The console reports rows and IPC bytes transferred.

The browser also supports `qw_query` with the sample graph alias `kg`, the `cypher` dialect, and an explicit schema. Both interfaces use the scalar schema parser shared with the native extension.

## Run locally

Use Node 24 and Rust with the `wasm32-unknown-unknown` target.

```sh
cd playground
rustup target add wasm32-unknown-unknown
npm ci
npm run dev
```

The build downloads the version-matched signed DuckDB JSON and Parquet extensions. The resulting site serves these and all runtime assets from the same origin. To build and test under the GitHub Pages project path, run `npm run build`, `npx playwright install chromium`, and `npm test`.

## Update the sample

The source data is in [data/papers.csv](data/papers.csv) and [data/citations.csv](data/citations.csv). Regenerate the bundled files with the DuckDB CLI.

```sh
python3 scripts/build-fixtures.py --duckdb /path/to/duckdb
```

## Deploy

The [Playground Pages workflow](../.github/workflows/PlaygroundPages.yml) builds the static artifact, runs the browser tests, and deploys from `main`. The repository's Pages publishing source is GitHub Actions.
