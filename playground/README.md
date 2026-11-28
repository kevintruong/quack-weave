# Quack Weave Playground

The playground runs SQL in DuckDB Wasm and Cypher in Ladybug Wasm. PaperTrail is a synthetic citation dataset bundled as a Cypher seed and a Parquet file. At startup, Ladybug builds a database in its own filesystem and reopens it read-only. DuckDB loads `papers` from Parquet.

The guided hybrid example uses a SQL/PGQ-style `GRAPH_TABLE` join. The browser bridge supports `GRAPH_TABLE (kg MATCH … [WHERE …] COLUMNS (…))`: Ladybug executes the graph pattern, predicates, and projections. Use plain ASCII column names and `AS` where needed. The bridge infers `BOOLEAN`, `BIGINT`, `DOUBLE`, and `VARCHAR` from Ladybug's result metadata and passes the projected rows to DuckDB via typed Arrow IPC. The console reports rows and IPC bytes transferred.

The browser also supports `qw_query` with the active graph alias `kg`, the `cypher` dialect, and an explicit schema. Both interfaces use the scalar schema parser shared with the native extension.

## Open a public Hugging Face graph

Choose **Hugging Face** under **Graph source**. Enter a dataset ID such as `ladybugdb/small-kgs`, a Hub dataset or file link, or a pinned `xet://datasets/<owner>/<repo>/<commit>/<file>.lbdb` URI. Click **Open graph**. For a repository with multiple snapshots, choose a **Database file** and click **Open graph** again.

The playground resolves the revision to a commit and attaches its public HTTPS file read-only in Ladybug Wasm. Ladybug reads byte ranges from the Hub as needed. Use a checkpointed database compatible with Ladybug 0.23. The selected file becomes graph `kg` in Cypher and hybrid SQL; the DuckDB `papers` table still contains PaperTrail. A failed open leaves the previous graph available.

For `kg_history/lbdb/kg_history.lbdb` in the example repository, run **Count relationships** to query the graph from DuckDB. The [tested revision](https://huggingface.co/datasets/ladybugdb/small-kgs/tree/9f306f6d19d191f4be480e04ed6dbcbe1e513782/kg_history/lbdb) returns 207.

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
