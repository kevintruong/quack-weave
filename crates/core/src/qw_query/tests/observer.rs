use std::sync::{
    Arc,
    atomic::{AtomicUsize, Ordering},
};

use super::{BackendError, Batch, BatchReader, ColumnSpec, Scan, batch, parse_schema};

#[derive(Clone)]
struct Observation {
    invocation: &'static str,
    sequence: Arc<AtomicUsize>,
}

impl Observation {
    fn emit(&self, event: &str, outcome: &str, value: &str) {
        let sequence = self.sequence.fetch_add(1, Ordering::Relaxed);
        println!(
            "QW_OBSERVATION\t1\tobserver.lifecycle\t{}\t{sequence}\t{event}\t{outcome}\t{value}",
            self.invocation
        );
    }
}

enum Pull {
    Row(Option<i64>),
    ArrowFailure,
}

struct ObservedReader {
    schema: Vec<ColumnSpec>,
    pulls: std::slice::Iter<'static, Pull>,
    observation: Observation,
}

impl BatchReader for ObservedReader {
    fn schema(&self) -> &[ColumnSpec] {
        self.observation.emit("schema", "read", "");
        &self.schema
    }

    fn next_batch(
        &mut self,
        _max_rows: usize,
        _max_bytes: Option<usize>,
    ) -> Result<Option<Batch>, BackendError> {
        match self.pulls.next() {
            Some(Pull::Row(value)) => {
                let batch = batch(*value);
                self.observation
                    .emit("pull", "batch", &batch.len.to_string());
                Ok(Some(batch))
            }
            Some(Pull::ArrowFailure) => {
                self.observation.emit("pull", "error", "QW_ARROW");
                Err(BackendError::Arrow)
            }
            None => {
                self.observation.emit("pull", "eof", "");
                Ok(None)
            }
        }
    }
}

impl Drop for ObservedReader {
    fn drop(&mut self) {
        self.observation.emit("release", "ok", "");
    }
}

fn observe_scan(invocation: &'static str, schema: &str, pulls: &'static [Pull], calls: usize) {
    let declared = parse_schema("id BIGINT").expect("valid declared schema");
    let actual = parse_schema(schema).expect("valid fixture schema");
    let observation = Observation {
        invocation,
        sequence: Arc::new(AtomicUsize::new(0)),
    };
    let mut scan = Scan::default();
    observation.emit("start", "ok", "");
    for _ in 0..calls {
        match scan.next(&declared, 1, None, || {
            observation.emit("launch", "ok", "");
            Ok(Box::new(ObservedReader {
                schema: actual.clone(),
                pulls: pulls.iter(),
                observation: observation.clone(),
            }))
        }) {
            // A returned batch has cleared core validation. DuckDB delivery is observed separately.
            Ok(Some(batch)) => observation.emit("batch_ready", "ok", &batch.len.to_string()),
            Ok(None) => observation.emit("scan_result", "eof", ""),
            Err(error) => {
                let error = error.to_string();
                let code = error
                    .split_ascii_whitespace()
                    .find(|word| word.starts_with("QW_"))
                    .and_then(|word| word.strip_suffix(':'))
                    .unwrap_or("unclassified");
                observation.emit("scan_result", "error", code);
            }
        }
    }
    drop(scan);
    observation.emit("end", "ok", "");
}

#[test]
fn fixture_observer_lifecycle() {
    // libtest's progress label can otherwise precede the first record on its line.
    println!();
    observe_scan(
        "eof",
        "id BIGINT",
        &[Pull::Row(Some(1)), Pull::Row(None)],
        4,
    );
    observe_scan("zero", "id BIGINT", &[], 2);
    observe_scan(
        "early_close",
        "id BIGINT",
        &[Pull::Row(Some(1)), Pull::Row(None)],
        1,
    );
    observe_scan("schema_mismatch", "wrong BIGINT", &[Pull::Row(Some(1))], 2);
    observe_scan("batch_error", "id BIGINT", &[Pull::ArrowFailure], 2);
    observe_scan(
        "late_batch_error",
        "id BIGINT",
        &[Pull::Row(Some(1)), Pull::ArrowFailure],
        3,
    );
}
