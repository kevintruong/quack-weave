use rusty_quack_core::qw_query::{
    BackendError, Batch, BatchReader, ColumnData, ColumnSpec, ScalarType,
};
use serde_json::Value;

use crate::batch_budget::reserve_slots;

enum Scalar {
    Null,
    Boolean(bool),
    BigInt(i64),
    Double(f64),
    Varchar(String),
}

pub(super) struct Rows {
    schema: Vec<ColumnSpec>,
    rows: std::vec::IntoIter<Vec<Scalar>>,
}

pub(super) fn decode(
    schema: Vec<ColumnSpec>,
    bytes: &[u8],
    typed: bool,
) -> Result<Rows, BackendError> {
    let mut reply: Value =
        serde_json::from_slice(bytes).map_err(|_| BackendError::RemoteTransport)?;
    let envelope = reply.as_object_mut().ok_or(BackendError::RemoteTransport)?;
    match envelope.get("errors") {
        None => (),
        Some(Value::Array(errors)) if errors.is_empty() => (),
        _ => return Err(BackendError::Execution),
    }
    if !typed {
        return Err(BackendError::Schema);
    }
    let Some(Value::Object(mut data)) = envelope.remove("data") else {
        return Err(BackendError::Schema);
    };
    let Some(Value::Array(fields)) = data.remove("fields") else {
        return Err(BackendError::Schema);
    };
    if fields.len() != schema.len()
        || fields.iter().zip(&schema).any(|(actual, expected)| {
            actual
                .as_str()
                .is_none_or(|actual| !actual.eq_ignore_ascii_case(&expected.name))
        })
    {
        return Err(BackendError::Schema);
    }
    let Some(Value::Array(rows)) = data.remove("values") else {
        return Err(BackendError::Schema);
    };
    let rows = rows
        .into_iter()
        .map(|row| {
            let Value::Array(row) = row else {
                return Err(BackendError::Schema);
            };
            if row.len() != schema.len() {
                return Err(BackendError::Schema);
            }
            row.into_iter()
                .zip(&schema)
                .map(|(cell, col)| scalar(cell, &col.data_type))
                .collect()
        })
        .collect::<Result<Vec<_>, _>>()?;
    Ok(Rows {
        schema,
        rows: rows.into_iter(),
    })
}

fn scalar(cell: Value, data_type: &ScalarType) -> Result<Scalar, BackendError> {
    let Value::Object(mut cell) = cell else {
        return Err(BackendError::Schema);
    };
    let value = cell.remove("_value").ok_or(BackendError::Schema)?;
    let tag = cell
        .get("$type")
        .and_then(Value::as_str)
        .ok_or(BackendError::Schema)?;
    Ok(match (data_type, tag, value) {
        (_, "Null", Value::Null) => Scalar::Null,
        (ScalarType::Boolean, "Boolean", Value::Bool(value)) => Scalar::Boolean(value),
        (ScalarType::BigInt, "Integer", Value::String(value)) => {
            Scalar::BigInt(value.parse().map_err(|_| BackendError::Schema)?)
        }
        (ScalarType::Double, "Float", Value::String(value)) => {
            let value: f64 = value.parse().map_err(|_| BackendError::Schema)?;
            if !value.is_finite() {
                return Err(BackendError::Schema);
            }
            Scalar::Double(value)
        }
        (ScalarType::Varchar, "String", Value::String(value)) => Scalar::Varchar(value),
        _ => return Err(BackendError::Schema),
    })
}

fn slot_size(data_type: &ScalarType) -> Result<usize, BackendError> {
    Ok(match data_type {
        ScalarType::Boolean => size_of::<Option<bool>>(),
        ScalarType::BigInt => size_of::<Option<i64>>(),
        ScalarType::Double => size_of::<Option<f64>>(),
        ScalarType::Varchar => size_of::<Option<String>>(),
        _ => return Err(BackendError::Schema),
    })
}

impl BatchReader for Rows {
    fn schema(&self) -> &[ColumnSpec] {
        &self.schema
    }

    fn next_batch(
        &mut self,
        max_rows: usize,
        max_bytes: Option<usize>,
    ) -> Result<Option<Batch>, BackendError> {
        if self.rows.len() == 0 {
            return Ok(None);
        }
        let len = self.rows.len().min(max_rows);
        if len == 0 {
            return Err(BackendError::BatchBudget);
        }
        if let Some(mut budget) = max_bytes {
            reserve_slots(&mut budget, self.schema.len(), size_of::<ColumnData>())?;
            for col in &self.schema {
                reserve_slots(&mut budget, len, slot_size(&col.data_type)?)?;
            }
            for cell in self.rows.as_slice()[..len].iter().flatten() {
                if let Scalar::Varchar(value) = cell {
                    reserve_slots(&mut budget, 1, value.len())?;
                }
            }
        }
        let mut columns = self
            .schema
            .iter()
            .map(|column| {
                Ok(match column.data_type {
                    ScalarType::Boolean => ColumnData::Boolean(Vec::with_capacity(len)),
                    ScalarType::BigInt => ColumnData::BigInt(Vec::with_capacity(len)),
                    ScalarType::Double => ColumnData::Double(Vec::with_capacity(len)),
                    ScalarType::Varchar => ColumnData::Varchar(Vec::with_capacity(len)),
                    _ => return Err(BackendError::Schema),
                })
            })
            .collect::<Result<Vec<_>, _>>()?;
        for row in self.rows.by_ref().take(len) {
            for (column, cell) in columns.iter_mut().zip(row) {
                match (column, cell) {
                    (ColumnData::Boolean(values), Scalar::Boolean(value)) => {
                        values.push(Some(value))
                    }
                    (ColumnData::BigInt(values), Scalar::BigInt(value)) => values.push(Some(value)),
                    (ColumnData::Double(values), Scalar::Double(value)) => values.push(Some(value)),
                    (ColumnData::Varchar(values), Scalar::Varchar(value)) => {
                        values.push(Some(value))
                    }
                    (ColumnData::Boolean(values), Scalar::Null) => values.push(None),
                    (ColumnData::BigInt(values), Scalar::Null) => values.push(None),
                    (ColumnData::Double(values), Scalar::Null) => values.push(None),
                    (ColumnData::Varchar(values), Scalar::Null) => values.push(None),
                    _ => return Err(BackendError::Schema),
                }
            }
        }
        Ok(Some(Batch { columns, len }))
    }
}
