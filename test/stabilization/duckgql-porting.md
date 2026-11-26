# DuckGQL SQLLogicTest ports

The stabilization gate runs 148 source-linked assertions from 11 [pinned DuckGQL suites](https://github.com/rahul-iyer/duckdb-gql/tree/b4421c5cb5e3a389f9658de591a0aa6d397da991/test/sql) on a [native Ladybug fixture](fixtures/duckgql_reads.cypher). Each assertion records its upstream filename and line in a `# Source` comment. The upstream [license](fixtures/DUCKGQL-LICENSE) accompanies the adapted SQL and fixtures.

| DuckGQL source suite | Source assertions ported | Local SQLLogicTest |
| --- | ---: | --- |
| `gql_basic_query.test` | 47 | [Basic reads](sqllogic/duckgql_basic.test) |
| `gql_global_aggregates.test` | 28 | [Aggregates](sqllogic/duckgql_aggregates.test) |
| `gql_parser.test` | 12 | [Admission](sqllogic/duckgql_admission.test) |
| `gql_read_only_database.test` | 4 | [Admission](sqllogic/duckgql_admission.test) |
| `gql_fixed_chain_access.test` | 9 | [Paths](sqllogic/duckgql_paths.test) |
| `gql_finite_range_global_modifiers.test` | 5 | [Paths](sqllogic/duckgql_paths.test) |
| `gql_composed_quantified.test` | 8 | [Paths](sqllogic/duckgql_paths.test) |
| `gql_reachability_paths.test` | 9 | [Reachability](sqllogic/duckgql_reachability.test) |
| `gql_shortest_target.test` | 9 | [Reachability](sqllogic/duckgql_reachability.test) |
| `gql_cast_collect.test` | 9 | [Scalars](sqllogic/duckgql_scalars.test) |
| `gql_exp_ln_functions.test` | 8 | [Scalars](sqllogic/duckgql_scalars.test) |

The ports use `qw_query(..., 'gql', ...)` for fixed directed patterns and GQL parser and admission assertions. Native Ladybug Cypher supplies scalar rows for optional matches, undirected edges, and recursive paths. DuckDB SQL applies aggregation, expressions, and pagination to those rows. The fixture uses stable scalar IDs where an upstream case observes an element ID. Several graph-object assertions project the fixture's scalar fields because the bridge exposes scalar types.

The path ports use Ladybug's explicit `TRAIL` mode where reusing an edge would change the result. The fixed-chain case with both endpoints bound uses a DuckDB left join over the matched paths so the output retains both parallel-edge rows. The shortest-path ports share the reachability fixture because its extra parallel edge leaves the minimum distances unchanged.

DuckGQL-specific storage and planner assertions exercise its own graph catalog, CSR indexes, optimizer settings, and DuckLake integration. Graph mutation cases require a writable engine surface. The Ladybug bench covers read semantics and read-only rejection, with a fixture checksum checked before and after each native suite run. The existing [multibatch scan](sqllogic/scan.test) checks native GQL delivery for 5,001 rows. The upstream generated feature corpus remains a source of candidates for future review.
