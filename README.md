# QuackWeave

QuackWeave is a native DuckDB extension for reading an existing local Ladybug graph. The MVP2 package supports standalone graph reads and SQL/PGQ graph table expressions. DuckDB can join their typed columns to its own tables and Parquet files. The explicit-schema `qw_query` interface is also available.

## Build and use MVP1

The native package targets macOS arm64, DuckDB `v2.0.1` and Ladybug `v0.22.3`. The build uses the Rust toolchain, a C++20 compiler, Python 3.12 or later, and OpenSSL 3 static libraries. It locates those libraries through Homebrew or `OPENSSL_LIB_DIR`.

```sh
make mvp1-deps
make mvp1
/path/to/duckdb-v2.0.1 -unsigned
```

Using an existing Ladybug graph with `Document` nodes and `LINKS_TO` relationships, run:

```sql
LOAD '/absolute/path/to/quack-weave/build/debug/extension/quack_weave/quack_weave.duckdb_extension';
SET GLOBAL qw_ladybug_config = '{"alias":"kg","path":"/absolute/path/to/documents.lbdb"}';

SELECT document_id
FROM qw_query(
    'kg', 'cypher',
    $$MATCH (:Document {id: 100})-[:LINKS_TO]->(doc:Document)
      RETURN doc.id AS document_id$$,
    schema := 'document_id BIGINT'
);
```

The `schema` argument accepts ordered `name TYPE` pairs using `BOOLEAN`, `BIGINT`, `DOUBLE`, or `VARCHAR`. The declared names and types must match the Cypher output. Configure the graph from a trusted DuckDB session with external access enabled. The optional `timeout_ms` setting applies a positive Ladybug query timeout.

Set `max_batch_bytes` to a positive integer to bound the size of each bridge-owned batch. An oversized batch raises `QW_BATCH_BUDGET` before its rows are published. Ladybug may still materialize the native result.

Interactive reads in one DuckDB instance reuse the registered graph's read-only Ladybug database handle. Each scan opens its own connection and applies the configured timeout. Use `RESET GLOBAL qw_ladybug_config` to release the registration before replacing the file, then register the new file with `SET GLOBAL`. Readers already holding a handle can finish their scans.

Run the native acceptance suite with version-matched DuckDB and Ladybug CLI binaries:

```sh
make mvp1-test DUCKDB=/path/to/duckdb-v2.0.1 LBUG=/path/to/lbug-v0.22.3
```

## Build and use MVP2

MVP2 adds a pinned DuckGQL parser and ANTLR C++ runtime to the macOS arm64 build for DuckDB `v2.0.1` and Ladybug `v0.22.3`. Install CMake in addition to the MVP1 build prerequisites.

```sh
make mvp2-deps
make mvp2
make mvp2-release
```

The artifacts are `build/mvp2/debug/extension/quack_weave/quack_weave.duckdb_extension` and `build/mvp2/release/extension/quack_weave/quack_weave.duckdb_extension`. The accompanying `licenses/` directory contains the GQL frontend notices for DuckGQL at revision `b4421c5cb5e3a389f9658de591a0aa6d397da991`, the openGQL grammar vendored at that revision, and ANTLR `4.13.2`. [DuckGQL](https://github.com/rahul-iyer/duckdb-gql/tree/b4421c5cb5e3a389f9658de591a0aa6d397da991) · [openGQL grammar](https://github.com/rahul-iyer/duckdb-gql/tree/b4421c5cb5e3a389f9658de591a0aa6d397da991/third_party/opengql) · [ANTLR](https://github.com/antlr/antlr4/tree/4.13.2)

Load the MVP2 artifact in DuckDB `v2.0.1` started with `-unsigned`, then configure the existing Ladybug graph as in MVP1.

```sql
LOAD '/absolute/path/to/quack-weave/build/mvp2/release/extension/quack_weave/quack_weave.duckdb_extension';
SET GLOBAL qw_ladybug_config = '{"alias":"kg","path":"/absolute/path/to/documents.lbdb"}';

SELECT document_id
FROM qw_query(
    'kg', 'gql',
    $$MATCH (src:Document)-[:LINKS_TO]->(doc:Document)
      FILTER src.id = 100
      RETURN doc.id AS document_id$$,
    schema := 'document_id BIGINT'
);
```

The explicit-schema GQL function supports one fixed, directed `MATCH` with named, labeled nodes and a relationship type. Use unquoted ASCII identifiers and omit the trailing semicolon inside the GQL payload. Return aliased scalar properties and optionally filter with one property-to-literal comparison using `WHERE`, `FILTER`, or `FILTER WHERE`. The literals are Boolean, signed integers, or strings.

The `schema` option and Ladybug timeout and batch limit settings apply to both dialects. Syntax errors use `QW_GQL_PARSE`, and valid syntax outside this subset uses `QW_GQL_SUBSET`. A Cypher-only MVP1 build reports `QW_GQL_UNAVAILABLE` for a GQL call.

Run package and runtime checks for both MVP2 artifacts with the pinned CLIs.

```sh
make mvp2-test DUCKDB=/path/to/duckdb-v2.0.1 LBUG=/path/to/lbug-v0.22.3
```

The default build remains MVP1 and its Cypher-only artifact stays under `build/debug` or `build/release`.

### Query a RelateDB graph alongside Ladybug

The optional `relate-provider` build embeds RelateDB 1.2.0. On macOS arm64, build it with `make mvp2-deps` and `make mvp2-relate-release`. Start DuckDB 2.0.1 with `-unsigned` and point the extension at an existing, checkpointed, single-file `.rl` bundle. [Pinned RelateDB source](https://github.com/relatedb/relate/tree/v1.2.0)

```sql
LOAD '/absolute/path/to/quack-weave/build/mvp2-relate/release/extension/quack_weave/quack_weave.duckdb_extension';
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

Run the integration suite with the pinned DuckDB SQLLogic runner and Ladybug CLI. It creates both real graph fixtures, checks the Relate rows through the native API, runs the DuckDB queries and verifies the fixture files after the reads. [SQLLogic cases](test/relate/provider.test) · [Fixture builder](crates/native/examples/relate_fixture.rs)

```sh
make mvp2-relate-test DUCKDB_UNITTEST=/path/to/duckdb-v2.0.1/unittest LBUG=/path/to/lbug-v0.22.3
```

The provider benchmark compares Ladybug and RelateDB through this same extension on matched LSQB message–creator graphs. [Results notebook](benchmarks/provider_comparison/provider_benchmark.ipynb) · [Reproduction instructions](benchmarks/provider_comparison/README.md)

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

Name the registered graph in `GRAPH_TABLE` and project the properties used by SQL. The following query ranks routes after matching destinations to a Parquet directory. The airport with the longest flight might have no directory row.

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

For a selective graph scan, write the predicate inside `GRAPH_TABLE`, for example `WHERE e.rid = 101` or `WHERE e.rid IN (101, 104)`. QuackWeave sends these predicates to Ladybug when the property is registered as `INT64` and the list contains at most 64 signed integer literals. DuckDB evaluates the original SQL predicate on the returned rows. Expressions, parameter values, and lists containing NULL use the ordinary DuckDB filter.

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

For a DuckDB table, use the same join, for example `JOIN watch AS w ON w.id = g.route_id`. When DuckDB builds a hash table on the watchlist and supplies a supported exact key filter, QuackWeave sends up to 64 `BIGINT` keys to Ladybug or an automatically discovered RelateDB graph. A single-key `JOIN watch USING (id)` also qualifies. DuckDB still performs the join, including duplicate matches, within the executing transaction. When the optimizer cannot supply an eligible filter, DuckDB joins the ordinary graph scan. `EXPLAIN (ANALYZE, FORMAT JSON)` shows how many rows the graph scan returned on that execution. [Table watchlist SQLLogic examples](test/stabilization/sqllogic/table_watchlist.test)

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

Use `qw_query` in a DuckDB `FROM` clause. Its declared `schema` supplies column names and types. Use `AS related(document_id)` to rename a column in SQL.

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

Host macros can apply an argument to a SQL filter in the same way. For an explicit-schema call, DuckDB can bind the complete graph payload and schema as table-function arguments during `EXECUTE`. Use a standalone statement to bind a value within a graph predicate.

Views store the SQL definition and resolve the current alias when DuckDB binds them. Repointing an alias can change the graph read by a view, including a prepared query through it. The generation check rejects an already-bound graph scan with `QW_CONFIG` if its configuration changes before the scan opens. A prepared call that binds its graph payload at `EXECUTE` can resolve the replacement graph. [Binding SQLLogicTests](test/stabilization/sqllogic/usage_binding.test)

One Ladybug alias is active per DuckDB instance. You can join Cypher and GQL results from that alias in one SQL query. Both dialects are read-only. Invoke DuckDB functions and macros on the rows returned to SQL, where the DuckDB catalog is available.

Plain `EXPLAIN` binds the query and can validate the GQL payload without opening Ladybug. `EXPLAIN ANALYZE` executes the plan and reports DuckDB operator timing and cardinalities. [Read boundary SQLLogicTests](test/stabilization/sqllogic/usage_boundary.test)

### Native stabilization

The macOS arm64 CI gate runs the pinned native DuckDB SQLLogicTest runner against the MVP2 debug and release packages and the Cypher-only MVP1 package. It also runs the native observer audit against MVP2 release. The DuckDB CLI serves other test targets, while this gate requires the `unittest` executable and `libduckdb.dylib` from the same DuckDB `v2.0.1` build at commit `8d78114e90a53823803660bf821f6073ac87da8c`. When configuring that checkout with CMake, use `-DDUCKDB_EXPLICIT_VERSION=v2.0.1 -DBUILD_UNITTESTS=ON`.

```sh
make mvp2-deps
make mvp2-stabilization-test \
  DUCKDB_UNITTEST=/path/to/duckdb-build/test/unittest \
  DUCKDB_LIB=/path/to/duckdb-build/src/libduckdb.dylib \
  LBUG=/path/to/lbug-v0.22.3
```

The gate writes profile logs, raw observer evidence, and `stabilization-coverage.json` under `build/stabilization-reports/`. The coverage check requires every manifest case across its assigned profiles and verifies the SQL source hashes against the checked-out files. Set `STABILIZATION_REPORT_DIR` to choose a different destination.

The [Ladybug GQL compatibility bench](test/stabilization/sqllogic/gql_compatibility.test) checks scalar results, row-bag equality with native Cypher, and the read-only GQL boundary. Both MVP2 profiles also run the [DuckGQL SQLLogicTest ports](test/stabilization/duckgql-porting.md) against a separate native Ladybug fixture. The runner compares the Ladybug fixtures before and after the suite.

## Rust extension template reference
This is an template for Rust based extensions based on the V2 C API of DuckDB. This repository will become a stable basis for pure-Rust DuckDB extensions that can be submitted to the Community extensions repository. 

It contains build pipelines for dynamic and wasm-based extensions. It is prefilled with example functions, so you can have an quick start with duckdb-neo!

Features:
- No DuckDB build required
- No C++ or C code required
- CI/CD chain preconfigured
- (Coming soon) Works with community extensions

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

The Cargo workspace contains three crates:

- `crates/core` (`rusty_quack_core`): the shared function implementations and registration.
- `crates/native` (`rusty_quack`): a native `cdylib` with the DuckDB extension entrypoint.
- `crates/wasm` (`rusty_quack_wasm`): a Wasm `staticlib` with the same entrypoint.

Both entrypoint crates depend on `rusty_quack_core`. Each feature lives in its own module under `crates/core/src/`,
and `crates/core/src/lib.rs` registers them; see [What the extension registers](#what-the-extension-registers).
Dependency versions and release settings are shared in the root `Cargo.toml`.

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

## Testing
This extension uses the DuckDB Python client for testing. This should be automatically installed in the `make configure` step.
The tests themselves are written in the SQLLogicTest format, just like most of DuckDB's tests. A sample test can be found in
`test/sql/<extension_name>.test`. To run the tests using the *debug* build:

```shell
make test_debug
```

or for the *release* build:
```shell
make test_release
```

### Version switching
Testing with different DuckDB versions is really simple:

First, run
```
make clean_all
```
to ensure the previous `make configure` step is deleted.

Then, run
```
DUCKDB_TEST_VERSION=v1.3.2 make configure
```
to select a different duckdb version to test with

Finally, build and test with
```
make debug
make test_debug
```

### Known issues
This is a bit of a footgun, but the extensions produced by this template may (or may not) be broken on windows on python3.11
with the following error on extension load:
```shell
IO Error: Extension '<name>.duckdb_extension' could not be loaded: The specified module could not be found
```
This was resolved by using python 3.12
