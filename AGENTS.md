# Quack-Weave agent guide

## Simplify first

1. Use the smallest change that solves the problem at the layer that owns it. Reuse the existing type, route, helper, or test runner. Add an abstraction, dependency, or setting only when a present requirement justifies it.
2. State assumptions that affect behavior. Define the expected result and how to check it before editing. Preserve local edits, keep the diff focused, and follow nearby code style.
3. Use `spurpower-code-explore` for code navigation. Start with `knowledge_context_pack_2` and follow its symbol references. Use `code_*` when the index is stale or you need exact text. Trace affected behavior through the public entry point and a nearby test.
4. Use spurpower-notebook-experiment with notebook MCP for notebook work. For nontrivial invariants or new bounds, check the rule catalog with `spurpower-solve` and use `jev_compile` when interpreting intent. Validate bindings and use Z3 for the encoded rule. Confirm compiled behavior with tests.

## Architecture to preserve

- **DuckDB owns SQL semantics.** `GRAPH_TABLE` lowers to a table function. DuckDB owns the residual joins, predicates, aggregation, ordering, and final `LIMIT`. Push down operations only when the rewrite preserves types, NULL behavior, row multiplicity, and observed order. Use the host route when eligibility cannot be proved.
- **Core owns policy and the typed batch contract.** `crates/core` binds queries and registration snapshots, handles supported GQL-to-Cypher conversion, chooses the route at scan initialization, and checks batches before writing DuckDB vectors.
- **Native wires the host and providers.** `crates/native` installs the DuckDB grammar and optimizer hooks, injects the GQL parser, and implements Ladybug, RelateDB, and Neo4j I/O behind `ReadBackend`, `ReadSession`, and `BatchReader`. Honor provider capabilities, FFI lifetimes, and the pinned DuckDB ABI. Keep `crates/wasm` and `template-compat` on the portable registration path.
- **An admitted reader stays on its generation.** A replacement before admission rejects a stale bound plan. An admitted reader can finish on its original session. Keep registration, permissions, credentials, and read limits at their existing boundaries. Use the dispatch log for the applied route and `EXPLAIN` for plan eligibility.

For the lifecycle and source map, see [core and native architecture](docs/core-native-architecture.ipynb).

## Tests for every code change

- Run the relevant unit tests for every code change, including changes with no SQLLogic case. For fixes and behavior changes, reproduce the failure first, add a focused regression, then verify it passes through the normal entry point.
- Add or update SQLLogic tests when SQL, a provider, an optimizer rule, or the benchmark snapshot contract changes. Use the pinned DuckDB runner and register stabilization cases in `test/stabilization/case_manifest.csv`. Use isolated fixtures and exact expected rows. Assert the schema where it matters, use a total order for ordered results, and preserve duplicates when comparing bags. Exercise both host and optimized paths and the expected fallback when a change touches dispatch.
- Use the existing Makefile, test runners, and CI entry points. `cargo fmt --all -- --check` checks Rust formatting. The CI-compatible portable unit suite is `cargo test --workspace --locked --no-default-features --features rusty_quack/template-compat`. Run the relevant native or Python unit suite for changes in those layers.

## Hybrid Query and release gate

Run the [Hybrid Query test bench](docs/hybrid-test-bench-guide.md) for changes to Hybrid Query semantics, routing, provider reads, or benchmark evidence. Before every release, run unit tests, native SQLLogic stabilization, and the test bench against the release artifact. Use `make native-stabilization-test` to build and check the native artifacts, or `make native-stabilization-test-prebuilt` with matching packaged artifacts and the pinned host.

Use the tiny `micro_creator_selective` SQLLogic witness and two fresh `mod32` tracker runs with both Ladybug and RelateDB and both arms. Compare the exact oracle result, workload identity, and observed schedule across runs. Check the applied route and graph scan counts for route changes. Keep the artifact and fixture hashes, SQLLogic receipts, and snapshot paths. Treat latency as comparative evidence under matched conditions. A timing result cannot substitute for correctness. Report any failed or blocked gate before calling the release verified.

Guidance adapted from [DuckDB AGENTS.md](../duckdb/AGENTS.md) and [Spur Notebook AGENTS.md](../spur-notebook/AGENTS.md).
