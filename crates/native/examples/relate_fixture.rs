//! Create the disposable single-file graph used by the Relate SQLLogic suite.
use std::{env, error::Error, path::Path};

use relate::{Database, Value};

fn main() -> Result<(), Box<dyn Error>> {
    let path = env::args().nth(1).ok_or("expected a new .rl file path")?;
    let destination = Path::new(&path);
    if destination.extension().and_then(|ext| ext.to_str()) != Some("rl") || destination.exists() {
        return Err("expected an unused .rl file path".into());
    }

    {
        let database = Database::open(&path)?;
        let mut writer = database.connect()?;
        writer.execute(
            "CREATE (o:airport {code: 'OSL', hub: true, score: 2.5}), \
             (a:airport {code: 'AMS'}), (b:airport {code: 'RIX'}), (:airport {code: 'BOS'}), \
             (o)-[:route {rid: 201, dist: 595}]->(a), \
             (o)-[:route {rid: 202, dist: 600}]->(a), (o)-[:route {rid: 203}]->(b)",
        )?;
        writer.execute(
            "CREATE (a:Item {id: 7, ID: 'seven'}), (b:Item {id: 8, ID: 'eight'}), \
             (a)-[:Item {id: 'edge', edge_only: true}]->(b)",
        )?;
        drop(writer);
        database.checkpoint()?;
    }

    // Check the persisted fixture through Relate itself before using DuckDB.
    let database = Database::open_read_only(&path)?;
    let mut reader = database.connect()?;
    let actual = reader.query(
        "MATCH (o:airport)-[r:route]->(d:airport) RETURN r.rid AS id, \
         d.code AS destination, r.dist AS miles ORDER BY id",
    )?;
    let expected = vec![
        vec![
            Value::Int(201),
            Value::String("AMS".into()),
            Value::Int(595),
        ],
        vec![
            Value::Int(202),
            Value::String("AMS".into()),
            Value::Int(600),
        ],
        vec![Value::Int(203), Value::String("RIX".into()), Value::Null],
    ];
    if actual.rows != expected {
        return Err(format!("unexpected native Relate fixture rows: {:?}", actual.rows).into());
    }
    Ok(())
}
