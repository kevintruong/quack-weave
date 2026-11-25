-- One row per provider, execution route and workload in each verified snapshot.
CREATE OR REPLACE TEMP MACRO qw_benchmark_history(snapshot_files) AS TABLE
SELECT id AS run_id, started_utc, workspace_head, binaries.extension AS extension_sha256,
       protocol, host_id, edge_count, fixture.files."edges.csv".sha256 AS fixture_sha256,
       blocks, runs, s.provider, s.scope, s.route, s."case" AS workload, s.n,
       s.p50_ms, s.p95_ms, s.cpu_p50_ms, s.qw_over_direct
FROM read_json(snapshot_files, format = 'unstructured', columns = {
    'id': 'VARCHAR', 'started_utc': 'TIMESTAMPTZ', 'workspace_head': 'VARCHAR',
    'protocol': 'INTEGER', 'host_id': 'VARCHAR', 'edge_count': 'BIGINT',
    'fixture': 'STRUCT(files STRUCT("edges.csv" STRUCT(sha256 VARCHAR)))',
    'binaries': 'STRUCT(extension VARCHAR)', 'blocks': 'INTEGER', 'runs': 'INTEGER',
    'summary': 'STRUCT(provider VARCHAR, scope VARCHAR, route VARCHAR, "case" VARCHAR,
                       n BIGINT, p50_ms DOUBLE, p95_ms DOUBLE, cpu_p50_ms DOUBLE, qw_over_direct DOUBLE)[]'
}), UNNEST(summary) AS series(s);
