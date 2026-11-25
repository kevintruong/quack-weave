//! Read-only scalar graph scans over a single Relate bundle.
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use relate::{Connection, Database, Value};
use rusty_quack_core::qw_query::{
    BackendError, Batch, BatchReader, ColumnData, ColumnSpec, GraphCatalog, GraphGeneration,
    GraphParameter, PreparedRegistration, ReadBackend, ReadSession, ScalarType,
};

mod admission;
mod catalog;
use crate::batch_budget::reserve_slots;
use admission::admit;

#[cfg(test)]
mod tests;

#[derive(Default)]
pub(crate) struct RelateBackend {
    registered: Mutex<Option<RegisteredDatabase>>,
}

struct RegisteredDatabase {
    generation: u64,
    path: PathBuf,
    database: Database,
}

fn open_database(path: &Path) -> Result<Database, BackendError> {
    if !path.is_file() || path.extension().is_none_or(|ext| ext != "rl") {
        return Err(BackendError::Open);
    }
    #[cfg(test)]
    tests::READ_OPENS.set(tests::READ_OPENS.get() + 1);
    Database::open_read_only(path.to_str().ok_or(BackendError::Open)?)
        .map_err(|_| BackendError::Open)
}

impl ReadBackend for RelateBackend {
    fn prepare_registration<'a>(
        &'a self,
        path: &Path,
        declared: Option<&GraphCatalog>,
        generation: u64,
    ) -> Result<PreparedRegistration<'a>, BackendError> {
        let database = open_database(path)?;
        let mut connection = database.connect().map_err(|_| BackendError::Open)?;
        let catalog = if declared.is_none() {
            Some(catalog::discover(&mut connection)?)
        } else {
            None
        };
        let populations = catalog
            .as_ref()
            .and_then(|_| catalog::populations(&mut connection));
        let registered = RegisteredDatabase {
            generation,
            path: path.into(),
            database,
        };
        Ok(PreparedRegistration {
            catalog,
            single_pattern_row_bound: populations.map(|(nodes, edges)| nodes.max(edges)),
            populations: populations.map(|(nodes, edges)| {
                rusty_quack_core::qw_query::GraphPopulations::ByEntity { nodes, edges }
            }),
            activate: Box::new(move || {
                *self
                    .registered
                    .lock()
                    .unwrap_or_else(|err| err.into_inner()) = Some(registered);
            }),
        })
    }

    fn set_generation(&self, _: Option<u64>) {
        self.registered
            .lock()
            .unwrap_or_else(|err| err.into_inner())
            .take();
    }

    fn projection(
        &self,
        catalog: &GraphCatalog,
        cypher: &str,
    ) -> Result<Vec<ColumnSpec>, BackendError> {
        admit(cypher, |stmt| catalog::projection(catalog, stmt))
    }

    fn native_gql(
        &self,
        query: String,
        _: Option<rusty_quack_core::qw_query::GqlParser>,
    ) -> duckdb_neo::Result<String> {
        rusty_quack_core::qw_query::compile_gql_query(&query, Some(crate::gql::parse_native))
    }

    fn runtime_watch_keys(&self, column: usize) -> Vec<i64> {
        crate::graph_entry::runtime_watch_keys(column)
    }

    fn open(
        &self,
        path: &Path,
        timeout_ms: Option<u64>,
    ) -> Result<Box<dyn ReadSession>, BackendError> {
        self.open_projected(path, timeout_ms, &[])
    }

    fn open_projected(
        &self,
        path: &Path,
        timeout_ms: Option<u64>,
        schema: &[ColumnSpec],
    ) -> Result<Box<dyn ReadSession>, BackendError> {
        self.session(path, timeout_ms, schema, None)
    }

    fn open_for_generation(
        &self,
        path: &Path,
        timeout_ms: Option<u64>,
        schema: &[ColumnSpec],
        generation: &GraphGeneration,
    ) -> Result<Box<dyn ReadSession>, BackendError> {
        self.session(path, timeout_ms, schema, Some(generation.id()))
    }
}

impl RelateBackend {
    fn connection(&self, path: &Path, generation: Option<u64>) -> Result<Connection, BackendError> {
        if let Some(id) = generation {
            let active = self.registered.lock().map_err(|_| BackendError::Open)?;
            if let Some(db) = active
                .as_ref()
                .filter(|db| db.generation == id && db.path == path)
            {
                // The connection retains the frozen store after the lock is released.
                return db.database.connect().map_err(|_| BackendError::Open);
            }
        }
        // A scan admitted just before SET/RESET must not replace the new generation.
        open_database(path)?
            .connect()
            .map_err(|_| BackendError::Open)
    }

    fn session(
        &self,
        path: &Path,
        timeout_ms: Option<u64>,
        schema: &[ColumnSpec],
        generation: Option<u64>,
    ) -> Result<Box<dyn ReadSession>, BackendError> {
        if timeout_ms.is_some() {
            return Err(BackendError::Timeout);
        }
        for column in schema {
            slot_size(&column.data_type)?;
        }
        let mut connection = self.connection(path, generation)?;
        let fallback_catalog = if schema.is_empty() {
            Some(catalog::discover(&mut connection)?)
        } else {
            None
        };
        Ok(Box::new(Session {
            connection,
            schema: schema.to_vec(),
            fallback_catalog,
        }))
    }
}

struct Session {
    connection: Connection,
    fallback_catalog: Option<GraphCatalog>,
    schema: Vec<ColumnSpec>,
}

impl ReadSession for Session {
    fn execute_with_params(
        mut self: Box<Self>,
        cypher: &str,
        params: &[(String, GraphParameter)],
    ) -> Result<Box<dyn BatchReader>, BackendError> {
        let columns = admit(cypher, |stmt| {
            if let Some(catalog) = &self.fallback_catalog {
                self.schema = catalog::projection(catalog, stmt)?;
            }
            let Some(relate_parser::Clause::Return(ret)) = stmt.clauses.last() else {
                return Err(BackendError::Admission);
            };
            Ok(ret
                .items
                .iter()
                .map(|item| (item.source_text.clone(), catalog::column_name(item)))
                .collect::<Vec<_>>())
        })?;
        let bindings = params
            .iter()
            .map(|(name, param)| {
                let value = match param {
                    GraphParameter::Null => Value::Null,
                    GraphParameter::Boolean(v) => Value::Bool(*v),
                    GraphParameter::Integer(v) => Value::Int(*v),
                    GraphParameter::Double(v) => Value::Float(*v),
                    GraphParameter::Text(v) => Value::String(v.as_str().into()),
                };
                (name.clone(), value)
            })
            .collect();
        let result = self
            .connection
            .query_with_params(cypher, bindings)
            .map_err(|_| BackendError::Execution)?;
        if result.header.columns.len() != self.schema.len()
            || result
                .header
                .columns
                .iter()
                .zip(&self.schema)
                .enumerate()
                .any(|(i, (native, expected))| {
                    native != &expected.name
                        && !columns.get(i).is_some_and(|(authored, column)| {
                            authored.as_ref() == Some(native)
                                && column.as_ref() == Some(&expected.name)
                        })
                })
        {
            return Err(BackendError::Schema);
        }
        Ok(Box::new(Rows {
            schema: self.schema,
            rows: result.rows.into_iter(),
        }))
    }
}

struct Rows {
    schema: Vec<ColumnSpec>,
    rows: std::vec::IntoIter<Vec<Value>>,
}

fn slot_size(ty: &ScalarType) -> Result<usize, BackendError> {
    Ok(match ty {
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
            for value in self.rows.as_slice()[..len].iter().flatten() {
                if let Value::String(s) = value {
                    reserve_slots(&mut budget, 1, s.len())?;
                }
            }
        }
        let mut columns = self
            .schema
            .iter()
            .map(|c| {
                Ok(match c.data_type {
                    ScalarType::Boolean => ColumnData::Boolean(Vec::with_capacity(len)),
                    ScalarType::BigInt => ColumnData::BigInt(Vec::with_capacity(len)),
                    ScalarType::Double => ColumnData::Double(Vec::with_capacity(len)),
                    ScalarType::Varchar => ColumnData::Varchar(Vec::with_capacity(len)),
                    _ => return Err(BackendError::Schema),
                })
            })
            .collect::<Result<Vec<_>, _>>()?;
        for row in self.rows.by_ref().take(len) {
            if row.len() != columns.len() {
                return Err(BackendError::Schema);
            }
            for (column, v) in columns.iter_mut().zip(row) {
                match (column, v) {
                    (ColumnData::Boolean(c), Value::Bool(v)) => c.push(Some(v)),
                    (ColumnData::BigInt(c), Value::Int(v)) => c.push(Some(v)),
                    (ColumnData::Double(c), Value::Float(v)) => c.push(Some(v)),
                    (ColumnData::Varchar(c), Value::String(v)) => c.push(Some(v.to_string())),
                    (ColumnData::Boolean(c), Value::Null) => c.push(None),
                    (ColumnData::BigInt(c), Value::Null) => c.push(None),
                    (ColumnData::Double(c), Value::Null) => c.push(None),
                    (ColumnData::Varchar(c), Value::Null) => c.push(None),
                    _ => return Err(BackendError::Schema),
                }
            }
        }
        Ok(Some(Batch { len, columns }))
    }
}
