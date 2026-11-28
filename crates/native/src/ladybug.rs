use std::ffi::{CStr, CString};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use duckdb_neo::connection::Context;
use rusty_quack_core::qw_query::{
    BackendError, Batch, BatchReader, CloudSource, CloudStorage, ColumnData, ColumnSpec,
    GraphCatalog, GraphGeneration, GraphParameter, GraphPopulations, OrderedWatchlistLimit,
    PreparedRegistration, ReadBackend, ReadSession, RetiredRegistration, ScalarType,
};

mod arrow;
mod catalog;
mod cloud;
mod ffi;

#[derive(Default)]
pub(crate) struct LadybugBackend {
    cache: Mutex<Option<Arc<DatabaseCache>>>,
}

struct DatabaseCache {
    generation: u64,
    database: Mutex<Option<(PathBuf, Arc<Mutex<Database>>)>>,
    cloud: cloud::Cache,
}

impl DatabaseCache {
    fn new(generation: u64) -> Arc<Self> {
        Arc::new(Self {
            generation,
            database: Mutex::new(None),
            cloud: cloud::Cache::default(),
        })
    }
}

impl LadybugBackend {
    fn generation_cache(
        &self,
        generation: &GraphGeneration,
    ) -> Result<Option<Arc<DatabaseCache>>, BackendError> {
        Ok(self
            .cache
            .lock()
            .map_err(|_| BackendError::Open)?
            .as_ref()
            .filter(|cache| cache.generation == generation.id())
            .cloned())
    }

    fn replace_cache(&self, next: Option<Arc<DatabaseCache>>) -> Option<RetiredRegistration> {
        let mut cache = self.cache.lock().unwrap_or_else(|err| err.into_inner());
        std::mem::replace(&mut *cache, next).map(|retired| Box::new(retired) as RetiredRegistration)
    }

    fn database(
        &self,
        path: &Path,
        generation: &GraphGeneration,
    ) -> Result<Arc<Mutex<Database>>, BackendError> {
        let cache = self.generation_cache(generation)?;
        // An admitted scan can keep its generation owner across SET/RESET. Its
        // lazy open cannot block the registry or replace the new generation's handle.
        let Some(cache) = cache else {
            return Ok(Arc::new(Mutex::new(Database::open(path, true)?)));
        };
        let mut database = cache.database.lock().map_err(|_| BackendError::Open)?;
        if let Some((cached_path, handle)) = &*database
            && cached_path == path
        {
            return Ok(Arc::clone(handle));
        }
        let handle = Arc::new(Mutex::new(Database::open(path, true)?));
        // Never publish an open that raced a replacement of the registered file.
        generation.validate(path).map_err(|_| BackendError::Open)?;
        *database = Some((path.to_owned(), Arc::clone(&handle)));
        Ok(handle)
    }
}

impl ReadBackend for LadybugBackend {
    fn runtime_watch_keys(&self, column: usize) -> Vec<i64> {
        crate::graph_entry::runtime_watch_keys(column)
    }

    fn ordered_watchlist_limit(&self) -> Option<OrderedWatchlistLimit> {
        crate::graph_entry::ordered_watchlist_limit()
    }

    fn ordered_watchlist_suffix(&self, order_column: usize, limit: u64) -> Option<String> {
        // Ladybug accepts an alias null test as a sort key. The grammar's
        // private aliases are built exclusively from trusted projection slots.
        let alias = format!("qw_col{order_column}");
        Some(format!(
            " ORDER BY ({alias} IS NULL), {alias} ASC LIMIT {limit}"
        ))
    }

    fn set_generation(&self, generation: Option<u64>) -> Option<RetiredRegistration> {
        self.replace_cache(generation.map(DatabaseCache::new))
    }

    fn catalog(&self, path: &Path) -> Option<rusty_quack_core::qw_query::GraphCatalog> {
        catalog::snapshot(path).map(|(catalog, _)| catalog)
    }

    fn prepare_registration<'a>(
        &'a self,
        path: &Path,
        _: Option<&GraphCatalog>,
        generation: u64,
    ) -> Result<PreparedRegistration<'a>, BackendError> {
        let (catalog, populations) = catalog::snapshot(path).unzip();
        Ok(PreparedRegistration {
            catalog,
            populations: populations.map(GraphPopulations::ByTable),
            single_pattern_row_bound: None,
            activate: Box::new(move || self.set_generation(Some(generation))),
        })
    }

    fn projection(
        &self,
        catalog: &rusty_quack_core::qw_query::GraphCatalog,
        cypher: &str,
    ) -> Result<Vec<ColumnSpec>, BackendError> {
        catalog::projection(catalog, cypher)
    }

    fn native_gql(
        &self,
        query: String,
        _: rusty_quack_core::qw_query::GqlParser,
    ) -> duckdb_neo::Result<String> {
        rusty_quack_core::qw_query::compile_gql_query(&query, crate::gql::parse_native)
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
        let database = Arc::new(Mutex::new(Database::open(path, true)?));
        Session::connect(database, timeout_ms, schema)
    }

    fn open_for_generation(
        &self,
        path: &Path,
        timeout_ms: Option<u64>,
        schema: &[ColumnSpec],
        generation: &GraphGeneration,
    ) -> Result<Box<dyn ReadSession>, BackendError> {
        Session::connect(self.database(path, generation)?, timeout_ms, schema)
    }

    fn supports_cloud_storage(&self, storage: CloudStorage) -> bool {
        matches!(
            storage,
            CloudStorage::S3 | CloudStorage::Gcs | CloudStorage::Xet
        )
    }

    fn prepare_cloud_registration<'a>(
        &'a self,
        context: &Context,
        source: &CloudSource,
        timeout_ms: Option<u64>,
        generation: u64,
    ) -> Result<PreparedRegistration<'a>, BackendError> {
        let cache = DatabaseCache::new(generation);
        let (catalog, scope) = cloud::prepare_registration(context, source, timeout_ms, &cache)?;
        Ok(PreparedRegistration {
            catalog: Some(catalog),
            populations: None,
            single_pattern_row_bound: None,
            activate: Box::new(move || {
                scope.track(&cache);
                self.replace_cache(Some(cache))
            }),
        })
    }

    fn open_cloud(
        &self,
        context: &Context,
        source: &CloudSource,
        timeout_ms: Option<u64>,
        schema: &[ColumnSpec],
        generation: &GraphGeneration,
    ) -> Result<Box<dyn ReadSession>, BackendError> {
        Ok(Box::new(cloud::Pending::new(
            context,
            source,
            timeout_ms,
            schema,
            self.generation_cache(generation)?,
        )?))
    }
}

impl Session {
    fn connect(
        database: Arc<Mutex<Database>>,
        timeout_ms: Option<u64>,
        schema: &[ColumnSpec],
    ) -> Result<Box<dyn ReadSession>, BackendError> {
        Ok(Box::new(Self::connect_native(
            database,
            timeout_ms,
            schema.iter().any(|column| column.data_type.is_nested()),
        )?))
    }

    fn connect_native(
        database: Arc<Mutex<Database>>,
        timeout_ms: Option<u64>,
        nested: bool,
    ) -> Result<Self, BackendError> {
        let mut connection = {
            let mut handle = database.lock().map_err(|_| BackendError::Open)?;
            Connection::open(&mut handle)?
        };
        if let Some(timeout_ms) = timeout_ms {
            let status =
                unsafe { ffi::lbug_connection_set_query_timeout(&mut connection.0, timeout_ms) };
            if status != ffi::SUCCESS {
                return Err(BackendError::Open);
            }
        }
        Ok(Session {
            connection,
            _database: database,
            nested,
            timeout_ms,
        })
    }
}

// Fields drop in declaration order, so the database outlives its connection.
struct Session {
    connection: Connection,
    _database: Arc<Mutex<Database>>,
    nested: bool,
    timeout_ms: Option<u64>,
}

// The native connection is documented as thread-safe. The session, prepared statement and
// result move together and Rust accesses them through exclusive ownership or &mut.
unsafe impl Send for Session {}

impl ReadSession for Session {
    fn execute_with_params(
        self: Box<Self>,
        cypher: &str,
        params: &[(String, GraphParameter)],
    ) -> Result<Box<dyn BatchReader>, BackendError> {
        self.execute_admitted(&admit_graph_read(cypher)?, params)
    }
}

fn admit_graph_read(cypher: &str) -> Result<CString, BackendError> {
    let cypher = CString::new(cypher).map_err(|_| BackendError::Admission)?;
    // Native read-only mode also permits some standalone commands. Require a graph read.
    if !unsafe { ffi::qw_ladybug_is_graph_read(cypher.as_ptr()) } {
        return Err(BackendError::Admission);
    }
    Ok(cypher)
}

impl Session {
    fn execute_admitted(
        mut self: Box<Self>,
        cypher: &CStr,
        params: &[(String, GraphParameter)],
    ) -> Result<Box<dyn BatchReader>, BackendError> {
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

        for (name, value) in params {
            let name = CString::new(name.as_str()).map_err(|_| BackendError::Execution)?;
            let status = unsafe {
                match value {
                    GraphParameter::Boolean(v) => {
                        ffi::lbug_prepared_statement_bind_bool(&mut prepared.0, name.as_ptr(), *v)
                    }
                    GraphParameter::Integer(v) => {
                        ffi::lbug_prepared_statement_bind_int64(&mut prepared.0, name.as_ptr(), *v)
                    }
                    GraphParameter::Double(v) => {
                        ffi::lbug_prepared_statement_bind_double(&mut prepared.0, name.as_ptr(), *v)
                    }
                    GraphParameter::Text(v) => ffi::qw_ladybug_bind_text(
                        &mut prepared.0,
                        name.as_ptr(),
                        v.as_ptr(),
                        v.len(),
                    ),
                    GraphParameter::Null => ffi::qw_ladybug_bind_text(
                        &mut prepared.0,
                        name.as_ptr(),
                        std::ptr::null(),
                        0,
                    ),
                }
            };
            if status != ffi::SUCCESS {
                return Err(BackendError::Execution);
            }
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
        let validated = arrow::read_schema_mode(&arrow_schema, self.nested);
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

// Moving the owning handle does not move the native database. Connection creation
// takes the shared mutex; each connection keeps the database alive until it drops.
unsafe impl Send for Database {}

impl Database {
    fn open(path: &Path, read_only: bool) -> Result<Self, BackendError> {
        let path =
            CString::new(path.as_os_str().as_encoded_bytes()).map_err(|_| BackendError::Open)?;
        let mut database = Self::default();
        let status =
            unsafe { ffi::qw_ladybug_open_database(path.as_ptr(), read_only, &mut database.0) };
        if status == ffi::SUCCESS && !database.0.ptr.is_null() {
            #[cfg(test)]
            if read_only {
                tests::READ_OPENS.set(tests::READ_OPENS.get() + 1);
            }
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
            #[cfg(test)]
            tests::CONNECTION_OPENS.set(tests::CONNECTION_OPENS.get() + 1);
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
