use super::*;

thread_local! {
    pub(super) static READ_OPENS: std::cell::Cell<usize> = const { std::cell::Cell::new(0) };
}

#[test]
fn registration_and_reads_share_one_open_per_generation() {
    use rusty_quack_core::qw_query::GraphGeneration;
    struct Fixture(std::path::PathBuf);
    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }
    let fixture =
        Fixture(std::env::temp_dir().join(format!("qw-relate-reuse-{}", std::process::id())));
    std::fs::create_dir(&fixture.0).unwrap();
    let path = fixture.0.join("small.rl");
    let writer = Database::open(path.to_str().unwrap()).unwrap();
    writer
        .connect()
        .unwrap()
        .execute("CREATE (:Item {id: 42})")
        .unwrap();
    writer.checkpoint().unwrap();
    drop(writer);
    let gen1 = GraphGeneration::capture(10, &path).unwrap();
    let gen2 = GraphGeneration::capture(11, &path).unwrap();
    let backend = RelateBackend::default();
    let schema = [ColumnSpec {
        name: "id".into(),
        data_type: ScalarType::BigInt,
    }];
    READ_OPENS.set(0);
    {
        let prepared = backend
            .prepare_registration(&path, None, gen1.id())
            .unwrap();
        assert!(prepared.catalog.is_some());
        (prepared.activate)();
    }
    let first = backend
        .open_for_generation(&path, None, &schema, &gen1)
        .unwrap();
    let second = backend
        .open_for_generation(&path, None, &schema, &gen1)
        .unwrap();
    assert_eq!(
        READ_OPENS.get(),
        1,
        "registration and two separate read sessions"
    );
    let other_path = path.with_file_name("missing.rl");
    assert!(matches!(
        backend.open_for_generation(&other_path, None, &schema, &gen1),
        Err(BackendError::Open)
    ));
    {
        let prepared = backend
            .prepare_registration(&path, Some(&GraphCatalog::new()), gen2.id())
            .unwrap();
        assert!(prepared.catalog.is_none());
        (prepared.activate)();
    }
    drop(
        backend
            .open_for_generation(&path, None, &schema, &gen2)
            .unwrap(),
    );
    assert_eq!(READ_OPENS.get(), 2);
    // A rejected registration drops its candidate without touching the live cache.
    drop(backend.prepare_registration(&path, None, 12).unwrap());
    drop(
        backend
            .open_for_generation(&path, None, &schema, &gen2)
            .unwrap(),
    );
    assert_eq!(READ_OPENS.get(), 3);
    // A delayed scan may open independently but cannot overwrite the current cache.
    drop(
        backend
            .open_for_generation(&path, None, &schema, &gen1)
            .unwrap(),
    );
    drop(
        backend
            .open_for_generation(&path, None, &schema, &gen2)
            .unwrap(),
    );
    assert_eq!(READ_OPENS.get(), 4);
    backend.set_generation(None);
    drop(backend);
    for session in [first, second] {
        let mut reader = session.execute("MATCH (n:Item) RETURN n.id AS id").unwrap();
        let batch = reader.next_batch(1, None).unwrap().unwrap();
        assert!(matches!(&batch.columns[..], [ColumnData::BigInt(v)] if v == &[Some(42)]));
    }
}

#[test]
fn admits_only_graph_reads_including_nested_expressions() {
    assert!(
        admit(
            "MATCH (p:Person) WHERE p.id = $id RETURN p.id AS id",
            |_| Ok(())
        )
        .is_ok()
    );
    assert!(admit("RETURN 'CALL dbms' AS text", |_| Ok(())).is_ok());
    for query in [
        "CREATE (p:Person) RETURN p",
        "MATCH (p) DELETE p RETURN 1 AS n",
        "RETURN 1 AS n; RETURN 2 AS n",
        "CALL db.labels() YIELD label RETURN label",
        "LOAD CSV FROM 'file:///tmp/a' AS line RETURN line",
        "RETURN EXISTS { CALL db.labels() YIELD label RETURN label } AS found",
        "RETURN unknownFunction(1) AS n",
    ] {
        assert!(
            matches!(admit(query, |_| Ok(())), Err(BackendError::Admission)),
            "{query}"
        );
    }
}

#[test]
fn budgets_batches_preserve_nulls_duplicates_and_report_type_mismatches() {
    let schema = vec![ColumnSpec {
        name: "id".into(),
        data_type: ScalarType::BigInt,
    }];
    let mut reader = Rows {
        schema,
        rows: vec![
            vec![Value::Int(7)],
            vec![Value::Null],
            vec![Value::Int(7)],
            vec![Value::Bool(true)],
        ]
        .into_iter(),
    };
    assert!(matches!(
        reader.next_batch(2, Some(1)),
        Err(BackendError::BatchBudget)
    ));
    let exact_budget = size_of::<ColumnData>() + 2 * size_of::<Option<i64>>();
    assert!(matches!(
        reader.next_batch(2, Some(exact_budget - 1)),
        Err(BackendError::BatchBudget)
    ));
    let first = reader.next_batch(2, Some(exact_budget)).unwrap().unwrap();
    assert!(matches!(&first.columns[..], [ColumnData::BigInt(v)] if v == &[Some(7), None]));
    let second = reader.next_batch(1, None).unwrap().unwrap();
    assert!(matches!(&second.columns[..], [ColumnData::BigInt(v)] if v == &[Some(7)]));
    assert!(matches!(
        reader.next_batch(1, None),
        Err(BackendError::Schema)
    ));
}

#[test]
fn discovered_projection_uses_exact_keys_and_rejects_mixed_properties() {
    let database = Database::open(":memory:").unwrap();
    let mut connection = database.connect().unwrap();
    connection
        .execute(
            "CREATE (a:Person {id: 1, ID: 'A', mixed: 1}), \
         (b:Employee:Person {id: 2, mixed: 'two'}), (a)-[:KNOWS {score: 1.5}]->(b)",
        )
        .unwrap();
    let graph = catalog::discover(&mut connection).unwrap();
    let backend = RelateBackend::default();
    let columns = backend
        .projection(
            &graph,
            "MATCH (a:Person)-[r:KNOWS]->(b:Person) WHERE a.id = -1 \
         RETURN a.id AS id, b.ID AS code, r.score AS score",
        )
        .unwrap();
    assert_eq!(
        columns.iter().map(|c| &c.data_type).collect::<Vec<_>>(),
        [
            &ScalarType::BigInt,
            &ScalarType::Varchar,
            &ScalarType::Double
        ]
    );
    for query in [
        "MATCH (a:Person) RETURN a.mixed AS x",
        "MATCH (a:Person) RETURN a.Id AS x",
    ] {
        assert_eq!(backend.projection(&graph, query), Err(BackendError::Schema));
    }
}

#[test]
fn same_named_node_and_edge_types_have_independent_catalogs() {
    let database = Database::open(":memory:").unwrap();
    let mut connection = database.connect().unwrap();
    connection
        .execute(
            "CREATE (a:Route {id: 'node', city: 'OSL'}), (b:Route), \
         (a)-[:Route {id: 42, miles: 7}]->(b)",
        )
        .unwrap();
    let graph = catalog::discover(&mut connection).unwrap();
    let backend = RelateBackend::default();
    let query = |items: &str| format!("MATCH (a:Route)-[r:Route]->(b:Route) RETURN {items}");
    let columns = backend
        .projection(
            &graph,
            &query("a.id AS nid, r.id AS rid, a.city AS city, r.miles AS miles"),
        )
        .unwrap();
    assert_eq!(
        columns.iter().map(|c| &c.data_type).collect::<Vec<_>>(),
        [
            &ScalarType::Varchar,
            &ScalarType::BigInt,
            &ScalarType::Varchar,
            &ScalarType::BigInt
        ]
    );
    for invalid in ["a.miles AS miles", "r.city AS city"] {
        assert_eq!(
            backend.projection(&graph, &query(invalid)),
            Err(BackendError::Schema)
        );
    }
}

#[test]
fn count_all_binds_a_bigint_even_for_an_empty_match() {
    let cols = RelateBackend::default()
        .projection(&GraphCatalog::new(), "MATCH (n) RETURN count(*) AS total")
        .unwrap();
    assert_eq!(
        cols,
        [ColumnSpec {
            name: "total".into(),
            data_type: ScalarType::BigInt
        }]
    );
}
