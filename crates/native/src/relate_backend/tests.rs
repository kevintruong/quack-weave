use super::*;

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
    let backend = RelateBackend;
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
    let backend = RelateBackend;
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
    let cols = RelateBackend
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
