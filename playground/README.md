# Quack Weave Playground

The playground runs SQL in DuckDB Wasm and Cypher in Ladybug Wasm. PaperTrail is a synthetic citation dataset bundled as a Cypher seed and a Parquet file. At startup, Ladybug builds a database in its own filesystem and reopens it read-only. DuckDB loads `papers` from Parquet.

For a hybrid query, the browser bridge finds explicit-schema `qw_query` calls in DuckDB's parsed SQL. It validates the schema with the same Rust parser used by the native extension, runs the Cypher in Ladybug, and stages only the returned rows in a temporary DuckDB table via typed Arrow IPC. The results report the number of rows and IPC bytes transferred. The bridge supports the sample graph alias `kg`, the `cypher` dialect, and a single SQL query with explicit `BOOLEAN`, `BIGINT`, `DOUBLE`, or `VARCHAR` result columns.

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
