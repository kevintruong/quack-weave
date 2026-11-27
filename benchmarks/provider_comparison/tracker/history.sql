-- One row per provider, execution route and workload in each verified snapshot.
CREATE OR REPLACE TEMP MACRO qw_benchmark_history(snapshot_files) AS TABLE
SELECT id AS run_id, started_utc, workspace_head, binaries.extension AS extension_sha256,
       protocol, host_id, edge_count, fixture.files."edges.csv".sha256 AS fixture_sha256,
       blocks, runs, s.provider, s.scope, s.route, s."case" AS workload, s.n,
       s.p50_ms, s.p95_ms, s.cpu_p50_ms, s.qw_over_direct,
       s.engine_execution.p50_ms AS engine_p50_ms, s.engine_execution.p95_ms AS engine_p95_ms,
       s.other_warm_work.p50_ms AS other_warm_work_p50_ms
FROM read_json(snapshot_files, format = 'unstructured', columns = {
    'id': 'VARCHAR', 'started_utc': 'TIMESTAMPTZ', 'workspace_head': 'VARCHAR',
    'protocol': 'INTEGER', 'host_id': 'VARCHAR', 'edge_count': 'BIGINT',
    'fixture': 'STRUCT(files STRUCT("edges.csv" STRUCT(sha256 VARCHAR)))',
    'binaries': 'STRUCT(extension VARCHAR)', 'blocks': 'INTEGER', 'runs': 'INTEGER',
    'summary': 'STRUCT(provider VARCHAR, scope VARCHAR, route VARCHAR, "case" VARCHAR,
                       n BIGINT, p50_ms DOUBLE, p95_ms DOUBLE, cpu_p50_ms DOUBLE, qw_over_direct DOUBLE,
                       engine_execution STRUCT(p50_ms DOUBLE, p95_ms DOUBLE), other_warm_work STRUCT(p50_ms DOUBLE))[]'
}), UNNEST(summary) AS series(s);

-- One sample per connection, summarized per route independently of workload count.
CREATE OR REPLACE TEMP MACRO qw_benchmark_bootstrap(snapshot_files) AS TABLE
SELECT id AS run_id, workspace_head, b.provider, b.route, b.n AS connections, b.p50_ms, b.p95_ms
FROM read_json(snapshot_files, format = 'unstructured', columns = {
    'id': 'VARCHAR', 'workspace_head': 'VARCHAR',
    'bootstrap_summary': 'STRUCT(provider VARCHAR, route VARCHAR, n BIGINT, p50_ms DOUBLE, p95_ms DOUBLE)[]'
}), UNNEST(bootstrap_summary) AS sessions(b);

-- Raw observations retain the measured phase and grain. Read only verified snapshots.
-- Numeric times and RSS, integral row counts, and opaque values use separate columns.
CREATE OR REPLACE TEMP MACRO qw_benchmark_metrics(snapshot_files) AS TABLE
WITH snapshots AS (
    SELECT row_number() OVER () AS snapshot_row, *
    FROM read_json(snapshot_files, format = 'unstructured', columns = {
        'id': 'VARCHAR', 'workspace_head': 'VARCHAR', 'protocol': 'INTEGER',
        'host_id': 'VARCHAR',
        'fixture': 'STRUCT(files STRUCT("edges.csv" STRUCT(sha256 VARCHAR)))',
        'binaries': 'STRUCT(extension VARCHAR)',
        'expected': 'MAP(VARCHAR, JSON)',
        'workload_evidence': 'MAP(VARCHAR, STRUCT(case_id VARCHAR, case_revision INTEGER, scale VARCHAR,
            fixture_sha256 VARCHAR, sql_sha256 VARCHAR, parameter_trace_sha256 VARCHAR,
            oracle_sha256 VARCHAR, workload_sha256 VARCHAR, oracle_key VARCHAR))',
        'workers': 'STRUCT(provider VARCHAR, route VARCHAR, block INTEGER, peak_rss_mib DOUBLE,
            setup STRUCT(bootstrap_ms DOUBLE),
            samples STRUCT("case" VARCHAR, repetition INTEGER, wall_ms DOUBLE, cpu_ms DOUBLE,
                           result_rows BIGINT, result_sha256 VARCHAR)[],
            engine_samples STRUCT("case" VARCHAR, repetition INTEGER, engine_ms DOUBLE,
                                  start_ns BIGINT, end_ns BIGINT)[],
            graph_scan_rows MAP(VARCHAR, BIGINT),
            scan_diagnostics MAP(VARCHAR, STRUCT(scan_rows BIGINT, applied_route VARCHAR,
                                               admitted_generation VARCHAR)))[]'
    })
),
workers AS (
    SELECT snapshot_row, w.*
    FROM snapshots, unnest(workers) AS worker(w)
),
release_samples AS (
    SELECT w.snapshot_row, w.provider, w.route, w.block, s."case" AS workload, s.repetition,
           s.wall_ms, s.cpu_ms, s.result_rows, s.result_sha256,
           map_extract_value(r.expected, coalesce(e.oracle_key, s."case")) AS oracle
    FROM workers w JOIN snapshots r USING (snapshot_row),
         unnest(w.samples) AS sample(s),
         LATERAL (SELECT map_extract_value(r.workload_evidence, s."case") AS e)
),
diagnostic_samples AS (
    SELECT snapshot_row, provider, route, block, s."case" AS workload, s.repetition, s.engine_ms,
           CASE WHEN s.end_ns >= s.start_ns
                THEN (s.end_ns - s.start_ns) / 1000000.0 - s.engine_ms END AS remainder_ms
    FROM workers, unnest(engine_samples) AS sample(s)
),
scans AS (
    SELECT snapshot_row, provider, route, block, workload,
           map_extract_value(graph_scan_rows, workload) AS graph_rows,
           map_extract_value(scan_diagnostics, workload) AS diagnostic
    FROM workers,
         unnest(list_distinct(list_concat(map_keys(graph_scan_rows), map_keys(scan_diagnostics)))) AS cases(workload)
),
observations AS (
    SELECT snapshot_row, provider, route, block, workload, repetition, metric_id,
           numeric_value, count_value, text_value, evidence_source
    FROM release_samples, LATERAL (VALUES
        (CASE WHEN repetition = 0 THEN 'first_fetch' ELSE 'release_wall' END, wall_ms, NULL, NULL, 'sample'),
        ('release_cpu', cpu_ms, NULL, NULL, 'sample'),
        ('result_rows', NULL, coalesce(result_rows, try_cast(json_extract(oracle, '$[0]') AS BIGINT)),
         NULL, CASE WHEN result_rows IS NOT NULL THEN 'sample' ELSE 'snapshot_oracle' END),
        ('result_digest', NULL, NULL, coalesce(result_sha256, json_extract_string(oracle, '$[1]')),
         CASE WHEN result_sha256 IS NOT NULL THEN 'sample' ELSE 'snapshot_oracle' END)
    ) AS metric(metric_id, numeric_value, count_value, text_value, evidence_source)

    UNION ALL
    SELECT snapshot_row, provider, route, block, workload, repetition, metric_id,
           numeric_value, NULL, NULL, 'engine_sample'
    FROM diagnostic_samples, LATERAL (VALUES
        ('engine_exec', engine_ms),
        ('engine_remainder', remainder_ms)
    ) AS metric(metric_id, numeric_value)

    UNION ALL
    SELECT snapshot_row, provider, route, block, workload, NULL, metric_id,
           NULL, count_value, text_value, evidence_source
    FROM scans, LATERAL (VALUES
        ('scan_rows', coalesce(graph_rows, diagnostic.scan_rows), NULL,
         CASE WHEN graph_rows IS NOT NULL THEN 'graph_scan_rows' ELSE 'scan_diagnostics' END),
        ('applied_route', NULL, diagnostic.applied_route, 'scan_diagnostics'),
        ('admitted_generation', NULL, diagnostic.admitted_generation, 'scan_diagnostics')
    ) AS metric(metric_id, count_value, text_value, evidence_source)

    UNION ALL
    SELECT snapshot_row, provider, route, block, NULL, NULL, metric_id,
           numeric_value, NULL, NULL, 'worker'
    FROM workers, LATERAL (VALUES
        ('bootstrap', setup.bootstrap_ms),
        ('peak_rss', peak_rss_mib)
    ) AS metric(metric_id, numeric_value)
),
definitions(metric_id, stage, unit, capture, sample_grain) AS (VALUES
    ('release_wall', 'client', 'ms', 'release', 'query'),
    ('release_cpu', 'client', 'ms', 'release', 'query'),
    ('bootstrap', 'host_setup', 'ms', 'release', 'connection'),
    ('first_fetch', 'client', 'ms', 'release', 'connection_case'),
    ('engine_exec', 'provider', 'ms', 'diagnostic', 'query'),
    ('engine_remainder', 'client', 'ms', 'diagnostic', 'query'),
    ('scan_rows', 'scan_boundary', 'rows', 'explain', 'query_scan'),
    ('result_rows', 'sql_output', 'rows', 'oracle', 'query'),
    ('result_digest', 'sql_output', 'sha256', 'oracle', 'query'),
    ('applied_route', 'scan_init', 'enum', 'logs', 'query_scan'),
    ('admitted_generation', 'scan_admission', 'opaque', 'logs', 'query_scan'),
    ('peak_rss', 'worker', 'mib', 'release', 'process')
)
SELECT r.id AS run_id, r.workspace_head, r.protocol, r.host_id,
       r.binaries.extension AS extension_sha256,
       o.provider, o.route, o.block, o.workload, o.repetition,
       e.case_id, e.case_revision, e.scale,
       coalesce(e.fixture_sha256, r.fixture.files."edges.csv".sha256) AS fixture_sha256,
       e.sql_sha256, e.parameter_trace_sha256, e.oracle_sha256, e.workload_sha256,
       o.metric_id, d.stage, d.capture, d.sample_grain, d.unit,
       o.numeric_value, o.count_value, o.text_value, o.evidence_source
FROM observations o JOIN snapshots r USING (snapshot_row)
JOIN definitions d USING (metric_id),
LATERAL (SELECT map_extract_value(r.workload_evidence, o.workload) AS e)
WHERE o.numeric_value IS NOT NULL OR o.count_value IS NOT NULL OR o.text_value IS NOT NULL;
