//! Build a fresh Relate .rl bundle from the benchmark's sorted SF1 projection CSV.
use relate::{Database, Value};
use std::{
    collections::BTreeMap,
    env,
    error::Error,
    fs::File,
    io::{BufRead, BufReader},
    path::Path,
};

fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = env::args().skip(1).collect();
    if let [mode, file, query] = args.as_slice()
        && mode == "--probe"
    {
        let db = Database::open_read_only(file)?;
        let result = db.connect()?.query(query)?;
        println!(
            "{} rows, first row {:?}",
            result.rows.len(),
            result.rows.first()
        );
        return Ok(());
    }
    if args.len() != 2 || Path::new(&args[1]).exists() {
        return Err("expected edges.csv and an unused .rl destination".into());
    }
    let db = Database::open(&args[1])?;
    let mut conn = db.connect()?;
    let mut groups = Vec::new();
    let mut mids = Vec::new();
    let mut author = None;
    let mut batch_rows = 0;
    let statement = "UNWIND $groups AS g CREATE (p:Person {PersonId:g[0]}) \
                     WITH p,g UNWIND g[1] AS mid \
                     CREATE (:Message {MessageId:mid})-[:Message_hasCreator_Person]->(p)";
    let flush = |groups: &mut Vec<Value>, conn: &mut relate::Connection| -> relate::Result<()> {
        let params = BTreeMap::from([(
            "groups".to_string(),
            Value::List(std::mem::take(groups).into()),
        )]);
        conn.query_with_params(statement, params)?;
        Ok(())
    };
    let mut lines = BufReader::new(File::open(&args[0])?).lines();
    if lines.next().transpose()?.as_deref() != Some("author,mid") {
        return Err("expected author,mid header".into());
    }
    for line in lines {
        let line = line?;
        let (a, m) = line.split_once(',').ok_or("invalid edge")?;
        let a: i64 = a.parse()?;
        if let Some(prev) = author {
            if a < prev {
                return Err("input must be grouped by author".into());
            }
            if prev != a {
                groups.push(Value::List(
                    vec![
                        Value::Int(prev),
                        Value::List(std::mem::take(&mut mids).into()),
                    ]
                    .into(),
                ));
                if batch_rows >= 4000 {
                    flush(&mut groups, &mut conn)?;
                    batch_rows = 0;
                }
            }
        }
        author = Some(a);
        mids.push(Value::Int(m.parse()?));
        batch_rows += 1;
    }
    if let Some(prev) = author {
        groups.push(Value::List(
            vec![Value::Int(prev), Value::List(mids.into())].into(),
        ));
        flush(&mut groups, &mut conn)?;
    }
    // Match the two primary-key access paths on the Ladybug fixture.
    conn.execute("CREATE RANGE INDEX author_key FOR (p:Person) ON (p.PersonId)")?;
    conn.execute("CREATE RANGE INDEX message_key FOR (m:Message) ON (m.MessageId)")?;
    drop(conn);
    db.checkpoint()?;
    Ok(())
}
