use std::ffi::{CStr, CString};
use std::path::Path;

use rusty_quack_core::qw_query::{
    BackendError, Batch, BatchReader, ColumnData, ColumnSpec, ReadBackend, ReadSession, ScalarType,
};

mod arrow;
mod catalog;
mod ffi;

pub(crate) struct LadybugBackend;

impl ReadBackend for LadybugBackend {
    fn catalog(&self, path: &Path) -> Option<rusty_quack_core::qw_query::GraphCatalog> {
        catalog::snapshot(path)
    }

    fn projection(
        &self,
        catalog: &rusty_quack_core::qw_query::GraphCatalog,
        cypher: &str,
    ) -> Result<Vec<ColumnSpec>, BackendError> {
        catalog::projection(catalog, cypher)
    }

    #[cfg(feature = "gql")]
    fn native_gql(
        &self,
        query: String,
        _: Option<rusty_quack_core::qw_query::GqlParser>,
    ) -> duckdb_neo::Result<String> {
        rusty_quack_core::qw_query::compile_gql_query(&query, Some(crate::gql::parse_native))
    }

    fn open(
        &self,
        path: &Path,
        timeout_ms: Option<u64>,
    ) -> Result<Box<dyn ReadSession>, BackendError> {
        let mut database = Database::open(path, true)?;
        let mut connection = Connection::open(&mut database)?;
        if let Some(timeout_ms) = timeout_ms {
            let status =
                unsafe { ffi::lbug_connection_set_query_timeout(&mut connection.0, timeout_ms) };
            if status != ffi::SUCCESS {
                return Err(BackendError::Open);
            }
        }
        Ok(Box::new(Session {
            connection,
            _database: database,
            timeout_ms,
        }))
    }
}

// Fields drop in declaration order, so the database outlives its connection.
struct Session {
    connection: Connection,
    _database: Database,
    timeout_ms: Option<u64>,
}

// The native connection is documented as thread-safe. The session, prepared statement and
// result move together and Rust accesses them through exclusive ownership or &mut.
unsafe impl Send for Session {}

impl ReadSession for Session {
    fn execute(mut self: Box<Self>, cypher: &str) -> Result<Box<dyn BatchReader>, BackendError> {
        let cypher = CString::new(cypher).map_err(|_| BackendError::Admission)?;

        // Parse before prepare. Native read-only mode deliberately permits some standalone
        // commands and does not by itself establish a row-returning graph statement.
        if !unsafe { ffi::qw_ladybug_is_graph_read(cypher.as_ptr()) } {
            return Err(BackendError::Admission);
        }

        let mut prepared = PreparedStatement::default();
        let status = unsafe {
            ffi::lbug_connection_prepare(&mut self.connection.0, cypher.as_ptr(), &mut prepared.0)
        };
        if status != ffi::SUCCESS
            || !unsafe { ffi::lbug_prepared_statement_is_success(&mut prepared.0) }
            || !unsafe { ffi::lbug_prepared_statement_is_read_only(&mut prepared.0) }
        {
            return Err(BackendError::Admission);
        }

        let mut result = QueryResult::default();
        let status = unsafe {
            ffi::lbug_connection_execute(&mut self.connection.0, &mut prepared.0, &mut result.0)
        };
        if status != ffi::SUCCESS {
            return Err(execution_error(self.timeout_ms.is_some()));
        }

        let mut arrow_schema = ffi::ArrowSchema::default();
        let status =
            unsafe { ffi::lbug_query_result_get_arrow_schema(&mut result.0, &mut arrow_schema) };
        if status != ffi::SUCCESS {
            #[cfg(test)]
            crate::test_observation::event("schema_rejected", "error", "");
            return Err(BackendError::Schema);
        }
        let validated = arrow::read_schema(&arrow_schema);
        #[cfg(test)]
        if validated.is_ok() {
            crate::test_observation::event("schema_accepted", "ok", "");
        } else {
            crate::test_observation::event("schema_rejected", "error", "");
        }
        let (schema, formats) = validated?;
        let remaining = unsafe { ffi::lbug_query_result_get_num_tuples(&mut result.0) };
        Ok(Box::new(Reader {
            result,
            _prepared: prepared,
            _session: self,
            schema,
            formats,
            remaining,
        }))
    }
}

// The result and prepared statement are destroyed before the connection and database.
struct Reader {
    result: QueryResult,
    _prepared: PreparedStatement,
    _session: Box<Session>,
    schema: Vec<ColumnSpec>,
    formats: Vec<arrow::ScalarFormat>,
    remaining: u64,
}

// The materialized result has one exclusive cursor. BatchReader only exposes &mut pulls and
// metadata copied into Rust memory; native and Arrow handles are never shared across readers.
unsafe impl Send for Reader {}

impl BatchReader for Reader {
    fn schema(&self) -> &[ColumnSpec] {
        &self.schema
    }

    fn next_batch(
        &mut self,
        max_rows: usize,
        max_bytes: Option<usize>,
    ) -> Result<Option<Batch>, BackendError> {
        if self.remaining == 0 {
            return Ok(None);
        }
        let requested = u64::try_from(max_rows)
            .map_err(|_| BackendError::Arrow)?
            .min(self.remaining);
        let chunk_size = i64::try_from(requested).map_err(|_| BackendError::Arrow)?;
        if chunk_size == 0 {
            return Err(BackendError::Arrow);
        }

        let mut array = ffi::ArrowArray::default();
        let status = unsafe {
            ffi::lbug_query_result_get_next_arrow_chunk(&mut self.result.0, chunk_size, &mut array)
        };
        if status != ffi::SUCCESS || array.length <= 0 || array.length > chunk_size {
            return Err(BackendError::Arrow);
        }

        let batch = arrow::read_batch(&array, &self.formats, max_bytes)?;
        self.remaining -= u64::try_from(batch.len).map_err(|_| BackendError::Arrow)?;
        Ok(Some(batch))
    }
}

fn execution_error(timeout_configured: bool) -> BackendError {
    let message = unsafe { ffi::lbug_get_last_error() };
    if message.is_null() {
        return BackendError::Execution;
    }
    // The pinned C API reports native cancellation and timeout as the same interrupt. This
    // adapter only installs the timeout and does not send external interrupts.
    let timed_out =
        timeout_configured && unsafe { CStr::from_ptr(message) }.to_bytes() == b"Interrupted.";
    unsafe { ffi::lbug_destroy_string(message) };
    if timed_out {
        BackendError::Timeout
    } else {
        BackendError::Execution
    }
}

#[derive(Default)]
struct Database(ffi::DatabaseHandle);

impl Database {
    fn open(path: &Path, read_only: bool) -> Result<Self, BackendError> {
        let path =
            CString::new(path.as_os_str().as_encoded_bytes()).map_err(|_| BackendError::Open)?;
        let mut database = Self::default();
        let status =
            unsafe { ffi::qw_ladybug_open_database(path.as_ptr(), read_only, &mut database.0) };
        if status == ffi::SUCCESS && !database.0.ptr.is_null() {
            Ok(database)
        } else {
            Err(BackendError::Open)
        }
    }
}

impl Drop for Database {
    fn drop(&mut self) {
        unsafe { ffi::lbug_database_destroy(&mut self.0) };
    }
}

#[derive(Default)]
struct Connection(ffi::ConnectionHandle);

impl Connection {
    fn open(database: &mut Database) -> Result<Self, BackendError> {
        let mut connection = Self::default();
        let status = unsafe { ffi::lbug_connection_init(&mut database.0, &mut connection.0) };
        if status == ffi::SUCCESS && !connection.0.ptr.is_null() {
            Ok(connection)
        } else {
            Err(BackendError::Open)
        }
    }
}

impl Drop for Connection {
    fn drop(&mut self) {
        unsafe { ffi::lbug_connection_destroy(&mut self.0) };
    }
}

#[derive(Default)]
struct PreparedStatement(ffi::PreparedHandle);

impl Drop for PreparedStatement {
    fn drop(&mut self) {
        unsafe { ffi::lbug_prepared_statement_destroy(&mut self.0) };
    }
}

#[derive(Default)]
struct QueryResult(ffi::QueryResultHandle);

impl Drop for QueryResult {
    fn drop(&mut self) {
        unsafe { ffi::lbug_query_result_destroy(&mut self.0) };
    }
}

#[cfg(test)]
mod tests;
