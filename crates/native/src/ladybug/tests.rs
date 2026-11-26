use super::*;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};

thread_local! {
    pub(super) static READ_OPENS: std::cell::Cell<usize> = const { std::cell::Cell::new(0) };
    pub(super) static CONNECTION_OPENS: std::cell::Cell<usize> = const { std::cell::Cell::new(0) };
}

static FIXTURE_ID: AtomicU64 = AtomicU64::new(0);

struct Fixture {
    directory: PathBuf,
    path: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let directory = std::env::temp_dir().join(format!(
            "qw-lbug-{}-{}",
            std::process::id(),
            FIXTURE_ID.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir(&directory).unwrap();
        let path = directory.join("fixture.lbdb");
        let mut database = Database::open(&path, false).expect("create Ladybug fixture");
        let mut connection = Connection::open(&mut database).expect("connect fixture");
        for cypher in [
            "CREATE NODE TABLE Person(id INT64, name STRING, PRIMARY KEY(id))",
            "CREATE (:Person {id: 1, name: 'one'}), (:Person {id: 2}), (:Person {id: 3, name: 'three'})",
            "CREATE REL TABLE KNOWS(FROM Person TO Person)",
            "MATCH (a:Person), (b:Person) WHERE a.id = 1 AND b.id = 2 CREATE (a)-[:KNOWS]->(b)",
        ] {
            let cypher = CString::new(cypher).unwrap();
            let mut result = QueryResult::default();
            let status = unsafe {
                ffi::lbug_connection_query(&mut connection.0, cypher.as_ptr(), &mut result.0)
            };
            assert_eq!(status, ffi::SUCCESS, "initialize fixture");
        }
        drop(connection);
        drop(database);
        Self { directory, path }
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        std::fs::remove_dir_all(&self.directory).unwrap();
    }
}

#[test]
fn interactive_reads_share_one_database_and_own_their_connections() {
    let fixture = Fixture::new();
    let backend = LadybugBackend::default();
    let first = GraphGeneration::capture(1, &fixture.path).unwrap();
    let second = GraphGeneration::capture(2, &fixture.path).unwrap();
    backend.set_generation(Some(first.id()));
    READ_OPENS.set(0);
    CONNECTION_OPENS.set(0);
    let mut readers = Vec::new();
    for timeout in [None, Some(10_000), None] {
        readers.push(
            backend
                .open_for_generation(&fixture.path, timeout, &[], &first)
                .unwrap()
                .execute("MATCH (p:Person) RETURN p.id AS id ORDER BY id")
                .unwrap(),
        );
    }
    assert_eq!(READ_OPENS.get(), 1, "three scans of the same generation");
    assert_eq!(CONNECTION_OPENS.get(), 3);
    // Invalidate the registration while its readers still own the old database.
    backend.set_generation(Some(second.id()));
    let next = backend
        .open_for_generation(&fixture.path, None, &[], &second)
        .unwrap();
    assert_eq!(READ_OPENS.get(), 2);
    drop(next);
    // A late scan for the old generation cannot evict the new generation.
    drop(
        backend
            .open_for_generation(&fixture.path, None, &[], &first)
            .unwrap(),
    );
    drop(
        backend
            .open_for_generation(&fixture.path, None, &[], &second)
            .unwrap(),
    );
    assert_eq!(READ_OPENS.get(), 3);
    backend.set_generation(None);
    drop(backend);
    for reader in &mut readers {
        let batch = reader.next_batch(1, None).unwrap().unwrap();
        assert!(matches!(&batch.columns[0], ColumnData::BigInt(ids) if ids == &[Some(1)]));
    }
}

#[test]
fn native_read_uses_typed_nullable_arrow_chunks_and_reaches_eof() {
    let fixture = Fixture::new();
    let mut result = LadybugBackend::default()
        .open(&fixture.path, None)
        .unwrap()
        .execute(
            "MATCH (p:Person) RETURN p.id AS id, p.name AS name, p.id > 1 AS flag,              CAST(p.id AS DOUBLE) AS score ORDER BY p.id",
        )
        .unwrap();
    let metadata: Vec<_> = result
        .schema()
        .iter()
        .map(|column| (column.name.as_str(), &column.data_type))
        .collect();
    assert_eq!(
        metadata,
        [
            ("id", &ScalarType::BigInt),
            ("name", &ScalarType::Varchar),
            ("flag", &ScalarType::Boolean),
            ("score", &ScalarType::Double),
        ]
    );

    let first = result.next_batch(2, None).unwrap().unwrap();
    assert_eq!(first.len, 2);
    assert!(
        matches!(&first.columns[0], ColumnData::BigInt(values) if values == &[Some(1), Some(2)])
    );
    assert!(
        matches!(&first.columns[1], ColumnData::Varchar(values) if values == &[Some("one".into()), None])
    );
    assert!(
        matches!(&first.columns[2], ColumnData::Boolean(values) if values == &[Some(false), Some(true)])
    );
    assert!(
        matches!(&first.columns[3], ColumnData::Double(values) if values == &[Some(1.0), Some(2.0)])
    );

    let last = result.next_batch(2, None).unwrap().unwrap();
    assert_eq!(last.len, 1);
    assert!(matches!(&last.columns[0], ColumnData::BigInt(values) if values == &[Some(3)]));
    assert!(result.next_batch(2, None).unwrap().is_none());
}

#[test]
fn read_only_admission_rejects_mutations_and_non_graph_commands() {
    let fixture = Fixture::new();
    let export_path = fixture.directory.join("export.csv");
    let copy = format!(
        "COPY (MATCH (p:Person) RETURN p.id) TO '{}'",
        export_path.display()
    );
    for query in [
        "CALL threads=1",
        "MATCH (p:Person) RETURN",
        "MATCH (p:Person) SET p.name = 'changed' RETURN p.id",
        "RETURN 1 AS id; MATCH (p:Person) DELETE p",
        "LOAD EXTENSION algo",
        "/* no statement */",
        &copy,
    ] {
        ffi::reset_native_calls();
        let error = LadybugBackend::default()
            .open(&fixture.path, None)
            .unwrap()
            .execute(query)
            .err();
        let calls = ffi::native_calls();
        assert_eq!(calls.execute, 0, "{query}: dispatched to Ladybug");
        assert_eq!(calls, ffi::NativeCalls::default(), "{query}");
        assert!(matches!(error, Some(BackendError::Admission)), "{query}");
    }
    assert!(!export_path.exists());
    let mut reader = LadybugBackend::default()
        .open(&fixture.path, None)
        .unwrap()
        .execute("MATCH (p:Person) RETURN p.name AS name ORDER BY p.id")
        .unwrap();
    let batch = reader.next_batch(3, None).unwrap().unwrap();
    assert!(matches!(&batch.columns[0], ColumnData::Varchar(values)
        if values == &[Some("one".into()), None, Some("three".into())]));
}

#[test]
fn empty_graph_result_preserves_schema() {
    let fixture = Fixture::new();
    let mut reader = LadybugBackend::default()
        .open(&fixture.path, None)
        .unwrap()
        .execute("MATCH (p:Person) WHERE p.id = 0 RETURN p.id AS id")
        .unwrap();
    assert_eq!(reader.schema()[0].data_type, ScalarType::BigInt);
    assert!(reader.next_batch(1, None).unwrap().is_none());
}

#[test]
fn unsupported_nested_result_fails_during_schema_admission() {
    let fixture = Fixture::new();
    ffi::reset_native_calls();
    let error = LadybugBackend::default()
        .open(&fixture.path, None)
        .unwrap()
        .execute("MATCH (p:Person) RETURN p AS node")
        .err();
    assert_eq!(
        ffi::native_calls(),
        ffi::NativeCalls {
            prepare: 1,
            read_only_check: 1,
            execute: 1,
            arrow_pull: 0,
        },
        "a rejected schema must never reach Arrow batch conversion",
    );
    assert!(matches!(error, Some(BackendError::Schema)));
}

#[test]
fn lowered_gql_uses_the_real_prepare_and_execute_boundary_once() {
    use rusty_quack_core::qw_query::compile_gql_query;

    let fixture = Fixture::new();
    let cypher = compile_gql_query(
        "MATCH (a:Person)-[:KNOWS]->(b:Person) WHERE a.id = 1 RETURN b.id AS id",
        crate::gql::parse,
    )
    .unwrap();

    ffi::reset_native_calls();
    let mut reader = LadybugBackend::default()
        .open(&fixture.path, None)
        .unwrap()
        .execute(&cypher)
        .unwrap();
    assert_eq!(
        ffi::native_calls(),
        ffi::NativeCalls {
            prepare: 1,
            read_only_check: 1,
            execute: 1,
            arrow_pull: 0,
        }
    );
    let batch = reader.next_batch(1, None).unwrap().unwrap();
    assert!(matches!(&batch.columns[0], ColumnData::BigInt(values) if values == &[Some(2)]));
    assert!(reader.next_batch(1, None).unwrap().is_none());
    assert_eq!(
        ffi::native_calls(),
        ffi::NativeCalls {
            prepare: 1,
            read_only_check: 1,
            execute: 1,
            arrow_pull: 1,
        }
    );
}

#[test]
fn lowered_gql_cannot_dispatch_after_native_prepare_fails() {
    use rusty_quack_core::qw_query::compile_gql_query;

    let fixture = Fixture::new();
    let cypher = compile_gql_query(
        "MATCH (a:Person)-[:KNOWS]->(b:Person) RETURN b.unknown_property AS id",
        crate::gql::parse,
    )
    .unwrap();
    let native_text = CString::new(cypher.as_str()).unwrap();
    assert!(unsafe { ffi::qw_ladybug_is_graph_read(native_text.as_ptr()) });

    ffi::reset_native_calls();
    let error = LadybugBackend::default()
        .open(&fixture.path, None)
        .unwrap()
        .execute(&cypher)
        .err();
    assert_eq!(
        ffi::native_calls(),
        ffi::NativeCalls {
            prepare: 1,
            read_only_check: 0,
            execute: 0,
            arrow_pull: 0,
        }
    );
    assert!(matches!(error, Some(BackendError::Admission)));
}

#[test]
fn native_batch_budget_counts_nullable_slots_and_owned_utf8() {
    let fixture = Fixture::new();
    let read = || {
        LadybugBackend::default()
            .open(&fixture.path, None)
            .unwrap()
            .execute("MATCH (p:Person) WHERE p.id = 3 RETURN p.name AS name")
            .unwrap()
    };
    let required = size_of::<ColumnData>() + size_of::<Option<String>>() + "three".len();
    println!("owned_batch_bytes={required}");

    let mut accepted = read();
    let batch = accepted.next_batch(1, Some(required)).unwrap().unwrap();
    assert!(matches!(&batch.columns[0], ColumnData::Varchar(values)
        if values == &[Some("three".into())]));
    drop(accepted);

    let mut denied = read();
    let result = denied.next_batch(1, Some(required - 1));
    assert!(
        matches!(result, Err(BackendError::BatchBudget)),
        "expected a budget error at {} bytes",
        required - 1
    );
}

fn observe_result(result: Result<Option<Batch>, BackendError>) {
    use crate::test_observation::event;

    match result {
        Ok(Some(batch)) => event("result", "ok", &batch.len.to_string()),
        Ok(None) => event("result", "eof", ""),
        Err(error) => event("result", "error", &format!("{error:?}")),
    }
}

fn observed_query(
    fixture: &Fixture,
    cypher: &str,
    timeout_ms: Option<u64>,
) -> Result<Box<dyn BatchReader>, BackendError> {
    ffi::reset_native_calls();
    LadybugBackend::default()
        .open(&fixture.path, timeout_ms)?
        .execute(cypher)
}

fn observe_first_batch(
    fixture: &Fixture,
    cypher: &str,
    timeout_ms: Option<u64>,
    max_bytes: Option<usize>,
) {
    match observed_query(fixture, cypher, timeout_ms) {
        Ok(mut reader) => observe_result(reader.next_batch(1, max_bytes)),
        Err(error) => observe_result(Err(error)),
    }
}

#[test]
fn fixture_observer_native_admission() {
    use crate::test_observation::{capture, event};
    use rusty_quack_core::qw_query::compile_gql_query;

    let fixture = Fixture::new();
    capture("observer.admission", "ast_rejected", None, || {
        observe_first_batch(&fixture, "CALL threads=1", None, None);
    });

    for (invocation, gql) in [
        (
            "prepare_rejected",
            "MATCH (a:Person)-[:KNOWS]->(b:Person) RETURN b.unknown_property AS id",
        ),
        (
            "admitted",
            "MATCH (a:Person)-[:KNOWS]->(b:Person) WHERE a.id = 1 RETURN b.id AS id",
        ),
    ] {
        capture(
            "observer.admission",
            invocation,
            None,
            || match compile_gql_query(gql, crate::gql::parse) {
                Ok(cypher) => observe_first_batch(&fixture, &cypher, None, None),
                Err(_) => event("result", "error", "GqlFrontend"),
            },
        );
    }
}

#[test]
fn fixture_observer_native_schema() {
    use crate::test_observation::capture;

    let fixture = Fixture::new();
    capture("observer.schema", "nested", None, || {
        observe_first_batch(&fixture, "MATCH (p:Person) RETURN p AS node", None, None);
    });
}

#[test]
fn fixture_observer_native_quota() {
    use crate::test_observation::{capture, event};

    let fixture = Fixture::new();
    let threshold = size_of::<ColumnData>() + size_of::<Option<String>>() + "three".len();
    for (invocation, budget) in [("at_budget", threshold), ("below_budget", threshold - 1)] {
        capture("observer.quota", invocation, None, || {
            event("threshold", "ok", &threshold.to_string());
            event("budget", "ok", &budget.to_string());
            observe_first_batch(
                &fixture,
                "MATCH (p:Person) WHERE p.id = 3 RETURN p.name AS name",
                None,
                Some(budget),
            );
        });
    }
}

#[test]
fn fixture_observer_native_faults() {
    use crate::test_observation::{Fault, capture};

    let fixture = Fixture::new();
    capture(
        "observer.failure",
        "arrow_after_batch",
        Some(Fault::ArrowAfterBatch),
        || match observed_query(
            &fixture,
            "MATCH (p:Person) RETURN p.id AS id ORDER BY p.id",
            None,
        ) {
            Ok(mut reader) => {
                observe_result(reader.next_batch(1, None));
                observe_result(reader.next_batch(1, None));
            }
            Err(error) => observe_result(Err(error)),
        },
    );

    for (invocation, fault, timeout_ms) in [
        ("timeout", Fault::Timeout, Some(1_000)),
        ("execution", Fault::Execution, None),
    ] {
        capture("observer.failure", invocation, Some(fault), || {
            observe_first_batch(&fixture, "RETURN 1 AS id", timeout_ms, None);
        });
    }
}
