use super::*;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};

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
fn native_read_uses_typed_nullable_arrow_chunks_and_reaches_eof() {
    let fixture = Fixture::new();
    let mut result = LadybugBackend
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
        "MATCH (p:Person) SET p.name = 'changed' RETURN p.id",
        "RETURN 1 AS id; MATCH (p:Person) DELETE p",
        "CALL threads=1",
        "LOAD EXTENSION algo",
        "/* no statement */",
        &copy,
    ] {
        let error = LadybugBackend
            .open(&fixture.path, None)
            .unwrap()
            .execute(query)
            .err();
        assert!(matches!(error, Some(BackendError::Admission)), "{query}");
    }
    assert!(!export_path.exists());
    let mut reader = LadybugBackend
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
    let mut reader = LadybugBackend
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
    let error = LadybugBackend
        .open(&fixture.path, None)
        .unwrap()
        .execute("MATCH (p:Person) RETURN p AS node")
        .err();
    assert!(matches!(error, Some(BackendError::Schema)));
}

#[test]
fn native_batch_budget_counts_nullable_slots_and_owned_utf8() {
    let fixture = Fixture::new();
    let read = || {
        LadybugBackend
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
