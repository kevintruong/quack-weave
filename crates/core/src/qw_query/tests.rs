use std::sync::{
    Arc,
    atomic::{AtomicUsize, Ordering},
};

use super::{
    BackendError, Batch, BatchReader, ColumnData, ColumnSpec, ScalarType, Scan, parse_schema,
};

mod observer;

#[test]
fn schema_preserves_order_and_rejects_case_folded_duplicates() {
    let schema = parse_schema("Name VARCHAR, id bigint").unwrap();
    assert_eq!(schema[0].name, "Name");
    assert_eq!(schema[1].data_type, ScalarType::BigInt);
    assert!(parse_schema("id BIGINT, ID BIGINT").is_err());
    assert!(parse_schema("id BIGINT,").is_err());
    assert!(parse_schema("id LIST").is_err());
    println!("JW_SCHEMA distinct=accepted folded_duplicate=rejected");
}

#[test]
fn config_accepts_an_opt_in_positive_batch_byte_quota() {
    let config =
        super::parse_config(r#"{"alias":"kg","path":"/fixture/graph.lbdb","max_batch_bytes":1}"#)
            .expect("operator can configure a one-byte quota");
    assert_eq!(config.max_batch_bytes, Some(1));
    let unlimited = super::parse_config(r#"{"alias":"kg","path":"/fixture/graph.lbdb"}"#)
        .expect("byte quota is optional");
    assert_eq!(unlimited.max_batch_bytes, None);
    assert!(
        super::parse_config(r#"{"alias":"kg","path":"/fixture/graph.lbdb","max_batch_bytes":0}"#)
            .is_err()
    );
    println!("JW_BUDGET positive=accepted zero=rejected absent=unchanged");
}

struct Reader {
    schema: Vec<ColumnSpec>,
    batches: std::vec::IntoIter<Batch>,
    drops: Arc<AtomicUsize>,
}

impl BatchReader for Reader {
    fn schema(&self) -> &[ColumnSpec] {
        &self.schema
    }

    fn next_batch(
        &mut self,
        _max_rows: usize,
        _max_bytes: Option<usize>,
    ) -> Result<Option<Batch>, BackendError> {
        Ok(self.batches.next())
    }
}

impl Drop for Reader {
    fn drop(&mut self) {
        self.drops.fetch_add(1, Ordering::Relaxed);
    }
}

fn batch(value: Option<i64>) -> Batch {
    Batch {
        columns: vec![ColumnData::BigInt(vec![value])],
        len: 1,
    }
}

#[test]
fn scan_starts_once_and_releases_on_eof() {
    let schema = parse_schema("id BIGINT").unwrap();
    let drops = Arc::new(AtomicUsize::new(0));
    let mut scan = Scan::default();
    let first = scan
        .next(&schema, 1, None, || {
            Ok(Box::new(Reader {
                schema: schema.clone(),
                batches: vec![batch(Some(1)), batch(None)].into_iter(),
                drops: drops.clone(),
            }))
        })
        .unwrap()
        .unwrap();
    assert!(matches!(&first.columns[0], ColumnData::BigInt(values) if values == &[Some(1)]));
    let second = scan
        .next(&schema, 1, None, || panic!("scan started twice"))
        .unwrap()
        .unwrap();
    assert!(matches!(&second.columns[0], ColumnData::BigInt(values) if values == &[None]));
    assert_eq!(drops.load(Ordering::Relaxed), 0);
    assert!(
        scan.next(&schema, 1, None, || panic!("scan restarted at EOF"))
            .unwrap()
            .is_none()
    );
    assert!(
        scan.next(&schema, 1, None, || panic!("exhausted scan restarted"))
            .unwrap()
            .is_none()
    );
    assert_eq!(drops.load(Ordering::Relaxed), 1);
    println!("JW_LIFECYCLE dispatches=1 publications=2 releases=1");
}

#[test]
fn schema_mismatch_prevents_output_and_releases_reader() {
    let expected = parse_schema("id BIGINT").unwrap();
    let drops = Arc::new(AtomicUsize::new(0));
    let mut scan = Scan::default();
    let error = scan
        .next(&expected, 1, None, || {
            Ok(Box::new(Reader {
                schema: parse_schema("different BIGINT").unwrap(),
                batches: vec![batch(Some(1))].into_iter(),
                drops: drops.clone(),
            }))
        })
        .err()
        .expect("mismatched schema should fail");
    assert!(error.to_string().contains("QW_SCHEMA"));
    assert_eq!(drops.load(Ordering::Relaxed), 1);
    assert!(
        scan.next(&expected, 1, None, || panic!("failed scan restarted"))
            .unwrap()
            .is_none()
    );
    println!("JW_LIFECYCLE schema_mismatch=rejected publications=0 releases=1");
}
