# QuackWeave

QuackWeave is a read-only graph extension for DuckDB. Its SQL/PGQ interface embeds `MATCH` inside a standard SQL `FROM` clause using `GRAPH_TABLE`. Project graph properties with `COLUMNS`, then join the result to a DuckDB table, a Parquet file, or another SQL relation.

[Read the documentation](https://kevintruong.github.io/quack-weave/docs/) for provider setup, query examples, and SQLLogic evidence. [Try GRAPH_TABLE in the browser Playground](https://kevintruong.github.io/quack-weave/) on the bundled PaperTrail sample. [Playground source and local setup](playground/README.md)

## Build and query a graph

Build one QuackWeave extension for DuckDB `v2.0.1` on Linux ARM64 or macOS ARM64. It includes Ladybug `v0.23.0`, RelateDB `v1.2.0`, and Neo4j AuraDB. Load it once, then register the graphs you want to query.

Install Rust, a C++20 compiler, CMake, Python 3.12 or later, and OpenSSL 3 static libraries. The build locates OpenSSL through Homebrew or `OPENSSL_LIB_DIR`. On Ubuntu 24.04 ARM64 set `CXX=g++-13` and `OPENSSL_LIB_DIR=/usr/lib/aarch64-linux-gnu`.

```sh
make native-deps && make native-release
/path/to/duckdb-v2.0.1 -unsigned
```

The commands build `build/native/release/extension/quack_weave/quack_weave.duckdb_extension`. Plain `make` produces the corresponding debug package in `build/native/debug/`. The adjacent `licenses/` directory contains the Quack Weave license and the notices for the pinned DuckDB, DuckGQL, openGQL, ANTLR, Ladybug, and RelateDB sources.

Open an existing Ladybug graph with `Document` nodes and `LINKS_TO` relationships. `GRAPH_TABLE` makes the matches available to standard SQL.

```sql
LOAD '/absolute/path/to/quack-weave/build/native/release/extension/quack_weave/quack_weave.duckdb_extension';
SET GLOBAL qw_ladybug_config = '{"alias":"kg","path":"/absolute/path/to/documents.lbdb"}';

WITH watch(id) AS (VALUES (101::BIGINT), (102::BIGINT))
SELECT g.id, g.title
FROM GRAPH_TABLE (
    kg MATCH (src:Document)-[edge:LINKS_TO]->(doc:Document)
    WHERE src.id = 100
    COLUMNS (doc.id AS id, doc.title AS title)
) AS g
JOIN watch USING (id)
ORDER BY g.id;
```

Use standalone `MATCH` for a graph-only result on a connection with a selected graph. Use `qw_query` for provider query text with a declared scalar schema and, in Cypher, named bindings. [SQL/PGQ queries](#hybrid-sql-queries) · [Standalone queries](#standalone-graph-queries) · [Explicit-schema queries](#explicit-schema-bridge)

## Inspect registered graphs

After loading a native package, list its installed providers and active aliases.

```sql
SELECT provider_id, setting_name, active_alias
FROM qw_graph_providers()
ORDER BY provider_id;
```

Each provider has one registration slot per DuckDB instance. `active_alias` is `NULL` until a graph is registered. Aliases are case-insensitive and unique across providers. When concurrent `SET GLOBAL` or `RESET GLOBAL` operations target the same slot, a stale registration fails with `QW_CONFIG` and the winning registration stays active. DuckDB publishes `current_setting()` after the extension callback, so use `active_alias` to inspect effective routing after concurrent updates.

## Graph providers

### Ladybug

Configure a trusted DuckDB session with external access enabled and register an existing `.lbdb` file using `qw_ladybug_config`. Use a positive `timeout_ms` to bound the Ladybug query, and a positive `max_batch_bytes` to bound each bridge-owned output batch. Ladybug may still materialize the native result.

Scans reuse the registered read-only database handle and open independent connections. Run `RESET GLOBAL qw_ladybug_config` before replacing the file, then register the replacement. Readers already holding a handle can finish their scans.

Run the package and runtime acceptance checks with the pinned CLIs.

```sh
make native-test DUCKDB=/path/to/duckdb-v2.0.1 LBUG=/path/to/lbug-v0.23.0
```

### Query a Ladybug snapshot in S3 or Google Cloud Storage

Publish a checkpointed `.lbdb` to a new object key and keep that key readable while admitted queries can still use it. Grant the runtime identity read access to the object and let it distinguish an absent WAL sidecar from an authorization failure. On S3, a missing key returns 404 only when the identity has `s3:ListBucket` on the bucket. A 403 aborts registration. The reader needs no write permissions. The native Ladybug adapter attaches the object through its embedded HTTPFS and runs GQL translated to Cypher or authored Cypher. DuckDB evaluates the surrounding SQL.

Provision a connection-scoped DuckDB `s3` or `gcs` secret with an explicit object URI or a bucket prefix ending in `/`. Load DuckDB's `httpfs` to register the secret type. Use an AWS region for S3 and interoperability HMAC credentials for GCS. The following example assumes that the executing connection already has a secret named `analytics_graph`.

```sql
SET GLOBAL qw_enable_remote_graphs = true;
SET GLOBAL qw_ladybug_config = '{
  "alias": "creator_graph",
  "path": "s3://analytics-graphs/snapshots/creator-v1.lbdb",
  "secret": "analytics_graph"
}';
SESSION SET GRAPH creator_graph;

MATCH (c:Creator)-[e:AUTHORED]->(p:Post)
RETURN c.id AS creator_id, p.id AS post_id;
```

Cloud HTTPS uses the OpenSSL trust store. Set `SSL_CERT_FILE` to a trusted CA bundle when the build-time default is unavailable. Ladybug applies its query timeout to each statement and bounds individual HTTP requests. Use a `gs://` URI for GCS. Create the scoped secret on each querying connection. Replacing a snapshot requires a new key and registration. Cloud snapshots use the host SQL route, including for `GRAPH_TABLE` joins. Azure Blob Storage and ADLS graph attachments are pending random-access support in the Ladybug Azure extension. [Cloud execution architecture](docs/core-native-architecture.ipynb)

### Query a RelateDB graph alongside Ladybug

Register an existing, checkpointed, single-file `.rl` bundle after you load QuackWeave. [Pinned RelateDB source](https://github.com/relatedb/relate/tree/v1.2.0)

```sql
SET GLOBAL qw_relate_config = '{"alias":"relate_routes","path":"/absolute/path/to/routes.rl"}';
SESSION SET GRAPH relate_routes;

MATCH (o:airport)-[r:route]->(d:airport)
WHERE o.code = 'OSL'
RETURN d.code AS destination, r.dist AS miles;
```

Use `GRAPH_TABLE` to join the graph to a DuckDB table. Here the two watchlist entries for flight 201 produce two matches. The fixture's flight 203 has a missing distance and returns SQL `NULL`.

```sql
WITH watch(rid) AS (VALUES (201), (201), (203))
SELECT g.rid, g.destination, g.miles
FROM GRAPH_TABLE (
    relate_routes MATCH (o:airport)-[r:route]->(d:airport)
    COLUMNS (r.rid AS rid, d.code AS destination, r.dist AS miles)
) AS g
JOIN watch AS w ON w.rid = g.rid
ORDER BY g.rid;
```

One Relate alias and one Ladybug alias can coexist. Give them distinct names and reference either alias in each `GRAPH_TABLE`, including both in the same SQL join. Standalone queries default to the extension's supported GQL subset. Select `SET SESSION qw_graph_dialect = 'cypher'` for Cypher. For a read with an explicit output schema, use `qw_query('relate_routes', 'cypher', query_text, schema := '...')`.

Registration opens the bundle read-only and ordinarily discovers property types from stored values. Discovery distinguishes a node label from a relationship type with the same name. For an empty graph or a property whose type cannot be inferred, declare the catalog at registration, for example `"catalog":{"airport":{"code":"VARCHAR"},"route":{"rid":"BIGINT","dist":"BIGINT"}}` inside the configuration JSON. A declared entry applies to both kinds if they share a name. The provider returns nullable `BOOLEAN`, `BIGINT`, `DOUBLE` and `VARCHAR` columns and checks returned values against the bound types.

Registration opens the frozen RelateDB bundle once. Subsequent scans on that DuckDB instance open independent connections to the registered handle. Use `RESET GLOBAL qw_relate_config` to release the registration before replacing the file. Active reads retain their snapshot until they finish. RelateDB 1.2.0 materializes its query result before QuackWeave converts it to DuckDB batches. The optional `max_batch_bytes` limits that conversion. Configuring `timeout_ms` for this provider raises `QW_CONFIG`. [RelateDB execution and buffering](https://github.com/relatedb/relate/blob/v1.2.0/docs/adr/0319-bolt-execution-failures-at-pull.md)

The provider benchmark compares Ladybug and RelateDB through this same extension on matched LSQB message–creator graphs. [Results notebook](benchmarks/provider_comparison/provider_benchmark.ipynb) · [Reproduction instructions](benchmarks/provider_comparison/README.md) [Latest main benchmark table](https://github.com/kevintruong/quack-weave/tree/benchmark-history) · [CI benchmark reports](benchmarks/provider_comparison/tracker/README.md#view-ci-benchmark-tables)

### Read from a Neo4j AuraDB graph

After loading the extension, configure AuraDB from a trusted DuckDB session with external access enabled. Use a database login with effective read-only privileges. Replace the sample origin, credentials, database, and graph pattern with values for your instance. Provision the secret on the DuckDB connection that will issue the reads.

```sql
CREATE SECRET routes IN connection (
    TYPE quack_weave_neo4j,
    ORIGIN 'https://example.databases.neo4j.io',
    USERNAME 'graph_reader',
    PASSWORD '<password>'
);
SET GLOBAL qw_enable_remote_graphs = true;
SET GLOBAL qw_neo4j_config = '{
  "alias":"routes_remote",
  "endpoint":"https://example.databases.neo4j.io",
  "database":"neo4j",
  "secret":"routes",
  "timeout_ms":5000,
  "max_response_bytes":1048576,
  "catalog":{"node:airport":{"code":"VARCHAR"}}
}';

SELECT destination
FROM qw_query(
    'routes_remote', 'cypher',
    $$MATCH (o:airport)-[:route]->(d:airport) WHERE o.code = $origin
      RETURN d.code AS destination$$,
    schema := 'destination VARCHAR', bindings := {'origin': 'OSL'}
);

SELECT destination
FROM GRAPH_TABLE (
    routes_remote MATCH (o:airport)-[e:route]->(d:airport)
    WHERE o.code = 'OSL' COLUMNS (d.code AS destination)
);
```

The adapter sends a single admitted Cypher read through AuraDB’s Query API v2 and decodes its Typed JSON scalar results. Set positive `timeout_ms` and `max_response_bytes` values to bound each read. `GRAPH_TABLE` requires a declared `catalog` with `node:Label` and `relationship:TYPE` keys for the properties referenced by the query. The example declares `node:airport` for `airport.code`. DuckDB evaluates the SQL projections, filters, joins, and aggregations for remote graph tables.

The secret's HTTPS origin must match the registered origin. An explicit `:443` is equivalent to the default port. Provision the same secret name on each pooled connection that uses the graph. Quack Weave looks up the credential when the scan starts, so `CREATE OR REPLACE SECRET routes IN connection (...)` takes effect for subsequent scans, including prepared statement execution. Revoke access on that connection with `DROP SECRET routes FROM connection` or close the connection. DuckDB's CLI can store literal `CREATE SECRET` SQL in its history. Supply actual credentials through your trusted application or through the environment option. [DuckDB `CREATE SECRET`](https://duckdb.org/docs/2.0/sql/statements/create_secret)

For process-wide provisioning, set `QW_NEO4J_ROUTES_ENDPOINT`, `QW_NEO4J_ROUTES_USERNAME`, and `QW_NEO4J_ROUTES_PASSWORD` before starting DuckDB, then use `"credential_ref":"routes"` in the graph configuration. The environment endpoint must match the registered endpoint exactly. The graph configuration accepts exactly one of `secret` and `credential_ref`.

`RESET GLOBAL qw_enable_remote_graphs` disables new remote scans. Run `make native-provider-test` with the pinned SQLLogic runner and Ladybug CLI to exercise RelateDB and the Neo4j local TLS fixture. The Neo4j fixture uses the `openssl` CLI to generate test certificates. [Neo4j SQLLogic tests](test/neo4j/sqllogic)

### Standalone graph queries

The usage notebook runs the same air-routes query in GQL and Cypher and shows where to place a SQL join and a row limit. [Usage patterns and executable example](quack-weave-hybrid-usage-spec.ipynb)

Register an existing Ladybug file once per DuckDB instance, then select the graph on each connection that will issue standalone queries. Registration captures the schema used to bind projected properties, including empty results.

```sql
SET GLOBAL qw_ladybug_config = '{"alias":"air_routes","path":"/absolute/path/to/air_routes.lbdb"}';
SESSION SET GRAPH air_routes;

MATCH (origin:airport)-[route:route]->(destination:airport)
WHERE origin.code = 'ATL'
RETURN origin.code AS origin, destination.code AS destination, route.dist AS miles
LIMIT 10;
```

The default standalone language is GQL. Use `SET SESSION qw_graph_dialect = 'cypher'` to select the Cypher read path. The loading connection and newly opened connections have the graph grammar enabled. On a connection opened before another connection loaded QuackWeave, run DuckDB's `CALL add_grammar_extension('quack_weave')` before selecting the graph. Parallel edges can produce duplicate rows and nullable properties can return SQL `NULL`. Supported features are a subset of the GQL and openCypher languages. [Standalone SQLLogic tests](test/stabilization/sqllogic/graph_entry.test)

Use named parameters for values in the graph predicate. DuckDB passes scalar values separately to Ladybug's prepared statement.

```sql
PREPARE flights AS
MATCH (o:airport)-[e:route]->(d:airport)
WHERE o.code = $origin
RETURN d.code AS destination, e.dist AS miles;

EXECUTE flights(origin := 'ATL');
```

Individual nodes and relationships retain Ladybug's identity and property fields as typed DuckDB structs. Relationship fields include `_ID`, `_SRC` and `_DST`. A supported named path projects ordered `_NODES` and `_RELS` lists. [Graph-value cases](test/stabilization/sqllogic/graph_values.test) · [Prepared graph statements](test/stabilization/sqllogic/graph_parameters.test)

### Hybrid SQL queries

Embed `MATCH` inside SQL's `FROM` clause with `GRAPH_TABLE`. Name the registered graph and project the properties used by SQL. The following query ranks routes after matching destinations to a Parquet directory. The airport with the longest flight might have no directory row.

```sql
SELECT r.origin, r.destination, a.city, r.miles
FROM GRAPH_TABLE (
    air_routes
    MATCH (o:airport)-[e:route]->(d:airport)
    WHERE o.code = 'ATL'
    COLUMNS (e.rid AS route_id, o.code AS origin,
             d.code AS destination, e.dist AS miles)
) AS r
JOIN read_parquet('airport_directory.parquet') AS a ON a.code = r.destination
ORDER BY r.miles DESC NULLS LAST, r.route_id
FETCH FIRST 2 ROWS ONLY;
```

The SQL/PGQ read surface supports named, labeled vertices and named, typed edges in fixed forward patterns. `COLUMNS` exposes the projected columns to SQL. Use a view or CTE to reuse them in subqueries, set operations or aggregates. DuckDB evaluates the outer join, ordering and row limit. [Hybrid fixture and SQLLogic examples](test/stabilization/sqllogic/hybrid_public.test)

For an unfiltered traversal, DuckDB can delegate a scalar `COUNT(*)` and `SUM` over a projected `BIGINT` to Ladybug. For example, `SELECT count(*), sum(route_id % 1000003) FROM routes` can fetch one aggregate row when `routes` is a view projecting the graph properties directly. The sum retains DuckDB's `HUGEINT` result type and returns `NULL` for empty or all-null input. [Aggregate SQLLogic examples](test/stabilization/sqllogic/graph_aggregate_pushdown.test)

With an automatically discovered RelateDB catalog, a scalar count or a sum such as `sum(route_id % 1000003)` can also return one graph row. Registration records the node and directed edge counts of the frozen snapshot. For a single vertex or a single directed step, QuackWeave uses those counts and the positive divisor to prove every intermediate sum fits RelateDB’s 64-bit integer accumulator. DuckDB computes unrestricted integer sums, multi-step aggregates and queries with an explicit batch budget. [RelateDB aggregate SQLLogic examples](test/relate/aggregate.test)

For a selective graph scan, you can write `WHERE e.rid = 101` inside `GRAPH_TABLE`, filter its SQL output with `WHERE g.route_id = 101`, or apply the same filter to a view that exposes `route_id`. When DuckDB binds an equality or a small `IN` list to a verified graph `BIGINT` property, QuackWeave sends the predicate to Ladybug or an automatically discovered RelateDB graph. It accepts bound lists containing up to 64 integer values. DuckDB retains the SQL predicate. The scan also uses DuckDB's requested column positions to fetch only the required properties on eligible reads. Authored native query text and reads with explicit resource limits preserve their original provider evaluation. [Predicate cases](test/relate/bound_filters.test) · [Projection cases](test/relate/bound_projection.test)

You can also supply the keys once in an SQL watchlist. In this example Ladybug reads matches for route IDs 101 and 104. DuckDB joins those matches to the original watchlist, so the two entries for 101 produce two result rows.

```sql
SELECT g.route_id, g.miles
FROM GRAPH_TABLE (
    air_routes MATCH (o:airport)-[e:route]->(d:airport)
    COLUMNS (e.rid AS route_id, e.dist AS miles)
) AS g
JOIN (VALUES (101::BIGINT), (104::BIGINT), (101::BIGINT)) AS w(id)
    ON w.id = g.route_id
ORDER BY g.route_id;
```

For a literal watchlist, use a graph on the left of an inner equality join, qualified keys, direct graph property projections and at most 64 `VALUES` rows. A graph-local predicate takes precedence. [SF1 literal watchlist benchmark](benchmarks/lsqb_sf1/watchlist.py)

For a DuckDB table, use the same join, for example `JOIN watch AS w ON w.id = g.route_id`. A view may reorder or rename the graph columns, and a single-key `JOIN watch USING (id)` also qualifies. When DuckDB builds its hash table on the watchlist and supplies an exact key filter, QuackWeave reads up to 64 `BIGINT` keys at execution time and sends them to the provider. A prepared statement therefore sees changes to the watchlist under DuckDB's transaction rules. DuckDB performs the join and preserves duplicate matches. If it builds the hash table on the graph side or supplies no eligible keys, it joins the ordinary scan. `EXPLAIN (ANALYZE, FORMAT JSON)` reports the graph rows returned on that execution. [Watchlist and transaction cases](test/stabilization/sqllogic/table_watchlist.test) · [Prepared join through a view](test/relate/bound_runtime.test)

The [SF1 usage benchmark notebook](benchmarks/lsqb_sf1/usage_regression.ipynb) compares the published Ladybug graph on two extension builds with direct Ladybug. It includes the executed watchlist and aggregate profiles, warm latency distributions, and the commands to repeat the measurements.

To reuse an existing GQL or Cypher query verbatim, execute it on a graph-enabled connection and ingest its Arrow result into the SQL consumer. This example uses two ADBC cursors. A limit inside `graph_statement` applies before the directory join.

```python
source.execute(graph_statement)
sink.adbc_ingest("route_result", source.fetch_arrow_table())
sink.execute("""
    SELECT r.destination, a.city, r.miles
    FROM route_result AS r
    JOIN airport_directory AS a ON a.code = r.destination
""")
```

The client acceptance target uses `adbc-driver-manager==1.9.0` and `pyarrow==23.0.1`. With those installed, run `make public-client-test` using the same `DUCKDB_LIB`, `DUCKDB_UNITTEST` and `LBUG` settings as the stabilization gate. [Executable ADBC example](test/public_client/run.py) · [SQLLogic result assertions](test/public_client/results.test)

### Explicit-schema bridge

Use `qw_query` in a DuckDB `FROM` clause. The required `schema` declares ordered column names and types using `BOOLEAN`, `BIGINT`, `DOUBLE`, or `VARCHAR`. The optional `bindings` DuckDB `STRUCT` supplies Boolean, integer, floating-point, string, or null values by name to a Cypher query. Use `AS related(document_id)` to rename a column in SQL. [Named binding SQLLogic tests](test/stabilization/sqllogic/declared_bindings.test)

The explicit-schema GQL bridge accepts a fixed directed `MATCH` with named, labeled nodes, a typed relationship, and aliased scalar properties. Use ASCII identifiers and omit the trailing semicolon inside the GQL payload. An optional property-to-literal comparison can use `WHERE`, `FILTER`, or `FILTER WHERE`. Syntax errors use `QW_GQL_PARSE`. Valid syntax outside this subset uses `QW_GQL_SUBSET`.

For a repeat graph read with fixed graph text and output types, prepare the explicit-schema statement on the DuckDB connection and reuse it. QuackWeave checks host access and the registration generation when the scan opens. Reprepare an already-bound call after its registration is replaced or reset. [ADBC example and checks](test/public_client/run.py)

```python
statement = """
SELECT * FROM qw_query('air_routes', 'cypher',
    $$MATCH (a:airport) WHERE a.code = $origin RETURN a.code AS code$$,
    schema := 'code VARCHAR', bindings := {'origin': 'ATL'})
"""
with connection.cursor() as lookup:
    lookup.adbc_prepare(statement)
    for _ in range(2):
        rows = lookup.execute(statement).fetch_arrow_table()
```

For embedded providers, bare `MATCH` reads the current session graph and dialect when DuckDB binds it. It also accepts named parameters in supported graph predicates. [Prepared lookup benchmark](benchmarks/provider_comparison/tracker/README.md#prepared-lookups)

Graph results follow DuckDB's relational semantics. Joins can multiply duplicate graph or SQL rows, and `UNION ALL` preserves duplicates. A scalar subquery returns `NULL` for zero rows and raises the default DuckDB error for multiple rows. `IN` follows SQL's three-valued logic, while `EXISTS` can correlate through a SQL predicate on graph-derived columns.

Use `AS MATERIALIZED` when a CTE should share a graph result across references. Inlining can produce separate graph scans. `WITH ORDINALITY` numbers rows in one scan's output. Use an outer `ORDER BY` with stable keys for reproducible ordering. [Relational SQLLogicTests](test/stabilization/sqllogic/usage_relations.test)

Bind input values in the host SQL whenever the graph query can remain fixed.

```sql
PREPARE count_linked AS
SELECT count(*)
FROM qw_query('kg', 'cypher',
    $$MATCH (a:Document {id: 100})-[:LINKS_TO]->(b:Document)
      RETURN b.id AS document_id$$,
    schema := 'document_id BIGINT')
WHERE document_id = $1;

EXECUTE count_linked(101);
```

Host macros can apply an argument to a SQL filter in the same way. Use `bindings` on a Cypher `qw_query` call to pass values into the graph predicate itself. DuckDB can also bind the complete graph payload and schema as table-function arguments during `EXECUTE`.

Views store the SQL definition and resolve the current alias when DuckDB binds them. Repointing an alias can change the graph read by a view, including a prepared query through it. The generation check rejects an already-bound graph scan with `QW_CONFIG` if its configuration changes before the scan opens. A prepared call that binds its graph payload at `EXECUTE` can resolve the replacement graph. [Binding SQLLogicTests](test/stabilization/sqllogic/usage_binding.test)

Each provider can have one active alias per DuckDB instance. You can join results from different configured graphs or from different supported query interfaces in one SQL query. Invoke DuckDB functions and macros on the returned rows, where the DuckDB catalog is available.

Plain `EXPLAIN` binds the query and can validate the GQL payload without opening Ladybug. `EXPLAIN ANALYZE` executes the plan and reports DuckDB operator timing and cardinalities. [Read boundary SQLLogicTests](test/stabilization/sqllogic/usage_boundary.test)

### Native stabilization

The ARM64 CI gate runs DuckDB's official SQLLogicTest runner against the native debug and release packages. It runs the observer audit against the release package. The runner and ADBC library come from DuckDB's release build for `v2.0.1` at commit `8d78114e90a53823803660bf821f6073ac87da8c`. [Pinned binary setup](benchmarks/provider_comparison/tracker/README.md#run)

```sh
make native-deps
make native-stabilization-test \
  DUCKDB_UNITTEST="$PWD/build/benchmark-host/unittest" \
  DUCKDB_LIB="$(find "$PWD/build/benchmark-host/release/src" -name 'libduckdb.*')" \
  LBUG=/path/to/lbug-v0.23.0
```

The gate writes profile logs, raw observer evidence, and `stabilization-coverage.json` under `build/stabilization-reports/`. The coverage check requires every manifest case across its assigned profiles and verifies the SQL source hashes against the checked-out files. Set `STABILIZATION_REPORT_DIR` to choose a different destination.

The Ladybug GQL compatibility tests check scalar results, row-bag equality with native Cypher, and read-only GQL admission. [Ladybug compatibility SQLLogic tests](test/stabilization/sqllogic/gql_compatibility.test) Both packages also run the [DuckGQL SQLLogicTest ports](test/stabilization/duckgql-porting.md) against a separate native Ladybug fixture. The runner compares the Ladybug fixtures before and after the suite.

## Rust extension template reference

The repository also includes the `rusty_quack` template targets for experimenting with DuckDB’s C API v2. `make debug`, `make release`, and the Wasm targets build the template entry points. Use the native targets above for QuackWeave’s graph providers.

## Cloning

Clone the repo with submodules

```shell
git clone --recurse-submodules <repo>
```

## Dependencies
In principle, these extensions can be compiled with the Rust toolchain alone. However, this template relies on some additional
tooling to make life a little easier and to be able to share CI/CD infrastructure with extension templates for other languages:

- Python3
- Python3-venv
- [Make](https://www.gnu.org/software/make)
- Git

Installing these dependencies will vary per platform:
- For Linux, these come generally pre-installed or are available through the distro-specific package manager.
- For MacOS, [homebrew](https://formulae.brew.sh/).
- For Windows, [chocolatey](https://community.chocolatey.org/).

## Project layout

The Cargo workspace contains three crates.

- `crates/core` owns provider registration, DuckDB table-function binding, and conversion of provider batches into DuckDB chunks. [Core source](crates/core)
- `crates/native` builds the `quack_weave` native extension. It wires the Ladybug, RelateDB, and Neo4j adapters and installs the C++ PEG grammar and optimizer hooks in GQL-enabled builds. [Native source](crates/native)
- `crates/wasm` builds the `rusty_quack` template functions for WebAssembly. [Wasm source](crates/wasm)

Both entry-point crates depend on `rusty_quack_core`. The root `Cargo.toml` sets workspace dependencies and release options. [Template functions](#what-the-extension-registers)

## Building
After installing the dependencies, building is a two-step process. Firstly run:
```shell
make configure
```
This will ensure a Python venv is set up with DuckDB and DuckDB's test runner installed. Additionally, depending on configuration,
DuckDB will be used to determine the correct platform for which you are compiling.

Then, to build the extension run:
```shell
make debug
```
This delegates the build process to cargo, which will produce a shared library in `target/debug/<shared_lib_name>`. After this step,
a script is run to transform the shared library into a loadable extension by appending a binary footer. The resulting extension is written
to the `build/debug` directory.

To create optimized release binaries, simply run `make release` instead.

### Running the extension
To run the extension code, start `duckdb` with `-unsigned` flag. This will allow you to load the local extension file.

```sh
duckdb -unsigned -cmd "LOAD '$PWD/build/debug/extension/rusty_quack/rusty_quack.duckdb_extension';"
```

The extension must be loaded into the exact DuckDB version it was built for (`TARGET_DUCKDB_VERSION` in the Makefile).

### WASM

To build for WASM targets, run `make wasm_eh`. This will create `./build/wasm_eh/release/rusty_quack.duckdb_extension.wasm`, that can then be used inside nodejs or an browser.

### Running the extension (WASM)
In this template there is an helper server that will locally host your extension. Just run
```bash
python3 scripts/host_wasm_target.py
```
Followed by opening https://shell.duckdb.org/?allowUnsignedExtensions=true, and loading the extension in:
```bash
INSTALL AND LOAD 'http://127.0.0.1:8000/rusty_quack.duckdb_extension.wasm';
```

### What the extension registers

The template is a small tour of what a Rust extension can register through DuckDB's C API v2. Every function is
documented, so `SELECT * FROM duckdb_functions() WHERE categories = ['rusty_quack']` lists them with descriptions and
examples.

| Module (`crates/core/src/`) | Feature of `duckdb-neo` | Try it |
|---|---|---|
| `scalar.rs` | scalar function with per-query init state | `SELECT rusty_echo('Jane')` |
| `quack.rs` | table function with bind data, global and local state | `SELECT * FROM rusty_quack(['Jane', 'Doe'])` |
| `aggregate.rs` | aggregate function: init, update, combine, finalize; order-independent | `SELECT rusty_longest(name) FROM t` |
| `sequence.rs` | chunked table function with projection and filter pushdown, cardinality and progress | `SELECT i FROM rusty_sequence(10000) WHERE i < 10` |
| `quack_type.rs` | custom type and a cast into it, with `CAST` and `TRY_CAST` semantics | `SELECT 3::QUACK, TRY_CAST(11 AS QUACK)` |
| `copy.rs` | copy format for `COPY ... TO` and `COPY ... FROM`, picked from the file extension | `COPY t TO 'ducks.quackfile'` |
| `replacement_scan.rs` | replacement scans: a quackfile path becomes a `read_quackfile` call, `quack` a subquery | `SELECT * FROM 'ducks.quackfile'`, `FROM quack` |
| `options.rs` | custom setting with validation, read by `rusty_quack` at bind time | `SET quack_emojis = ['🦆', '🦀']` |
| `macros.rs` | table macro | `SELECT * FROM glaze()` |
| `pragma.rs` | query pragma with state kept across calls | `PRAGMA duck_count('🦆🦆')` |

```sql
SELECT rusty_echo('Jane');
```

```
┌─────────────────────┐
│ rusty_echo('Jane')  │
│       varchar       │
├─────────────────────┤
│ 🐤 Jane 🦀 Jane     │
└─────────────────────┘
```

```sql
SELECT * FROM rusty_quack(['Jane', 'Doe', 'Loves', 'Ducks']);
```

```
┌─────────┬─────────┬───────────────────────┬─────────────┐
│  name   │  icon   │      concat_name      │ total_index │
│ varchar │ varchar │        varchar        │   uint64    │
├─────────┼─────────┼───────────────────────┼─────────────┤
│ Ducks   │ 🐤      │ Ducks|                │           0 │
│ Loves   │ 🦀      │ Ducks|Loves|          │           1 │
│ Doe     │ 🐥      │ Ducks|Loves|Doe|      │           2 │
│ Jane    │ 🐤      │ Ducks|Loves|Doe|Jane| │           3 │
└─────────┴─────────┴───────────────────────┴─────────────┘
```

`EXPLAIN` shows the optimizer hooks at work. The scan lists only the projected columns, and there is
no `Filter` node: `rusty_sequence` claimed `i < 5` in `pushdown_filter`, so DuckDB dropped its own copy
and the function enforces the filter while scanning.

```sql
EXPLAIN SELECT i FROM rusty_sequence(10000) WHERE i < 5;
```

```
╭─ Rusty Sequence ─────────╮
│ Function: RUSTY_SEQUENCE │
│ Projections: i           │
│ ~10,000 rows             │
╰──────────────────────────╯
```

The `~10,000 rows` is the cardinality that `bind` declared with `set_cardinality`; it is reported before
any filter is pushed down and cannot be revised afterwards, so it stays at the full count even though the
query returns 5 rows. A filter the function does not claim keeps its own node:

```sql
EXPLAIN SELECT i FROM rusty_sequence(10000) WHERE i > 9995;
```

```
╭─ Filter ─────────────────╮
│ Expression: i > 9995     │
│ ~2,000 rows              │
╰─────────────┬────────────╯
╭─ Rusty Sequence ─────────╮
│ Function: RUSTY_SEQUENCE │
│ Projections: i           │
│ ~10,000 rows             │
╰──────────────────────────╯
```

## Template testing
The template tests use the DuckDB Python client. This should be automatically installed in the `make configure` step.
The tests themselves are written in the SQLLogicTest format, just like most of DuckDB's tests. A sample test can be found in
`test/sql/<extension_name>.test`. To run the tests using the *debug* build:

```shell
make test_debug
```

or for the *release* build:
```shell
make test_release
```

### DuckDB version alignment

Build and load the extension against the DuckDB version pinned in the `Makefile`. A native version upgrade also needs matching C API v2 bindings, C++ grammar headers, and test binaries. [Native build configuration](crates/native/build.rs)

### Known issues
This is a bit of a footgun, but the extensions produced by this template may (or may not) be broken on windows on python3.11
with the following error on extension load:
```shell
IO Error: Extension '<name>.duckdb_extension' could not be loaded: The specified module could not be found
```
This was resolved by using python 3.12

## License

Quack Weave is distributed under the [Apache License 2.0](LICENSE). Third-party components retain their respective licenses.
