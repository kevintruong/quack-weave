//! Read-only Ladybug results exposed as a DuckDB table function.

use std::{
    collections::{BTreeMap, HashSet},
    num::NonZeroUsize,
    path::Path,
    sync::{
        Arc,
        atomic::{AtomicU64, Ordering},
    },
};

use duckdb_neo::{
    DuckDBType, FromValue, Result, ToValue,
    bind_arguments::BindArguments,
    connection::{Context, SettingScope},
    custom_option::{CustomOptionBuilder, CustomOptionCallbacks},
    data_chunk::DataChunk,
    error::Error,
    extension::Extension,
    file::{FileBuilder, FileSystem},
    logical_type::LogicalType,
    signature::{
        FunctionDocumentationBuilder, FunctionParameter, FunctionParameterKind, SignatureBuilder,
    },
    table_function::{
        BindFunctionHandle, ExecColumnInfo, InitColumnData, TableFunctionBuilder,
        TableFunctionCallbacks,
    },
    value::Value,
    vector::WritableNativeElement,
};
use serde::{Deserialize, Serialize};

mod gql;

pub use gql::{GqlParser, compile_gql_query};

const CONFIG: &str = "qw_ladybug_config";
static CONFIG_GENERATION: AtomicU64 = AtomicU64::new(0);

/// Table and property names with their Ladybug logical types, captured at registration.
pub type GraphCatalog = BTreeMap<String, Vec<(String, String)>>;

/// A backend that exclusively opens read-only database handles.
pub trait ReadBackend: Send + Sync {
    /// Read only catalog metadata while registering a graph generation.
    fn catalog(&self, _path: &Path) -> Option<GraphCatalog> {
        None
    }

    /// Resolve the projection using the saved metadata, without opening the graph.
    fn projection(
        &self,
        _catalog: &GraphCatalog,
        _cypher: &str,
    ) -> std::result::Result<Vec<ColumnSpec>, BackendError> {
        Err(BackendError::Schema)
    }

    fn native_gql(&self, query: String, parser: Option<GqlParser>) -> Result<String> {
        compile_gql_query(&query, parser)
    }

    fn open(
        &self,
        path: &Path,
        timeout_ms: Option<u64>,
    ) -> std::result::Result<Box<dyn ReadSession>, BackendError>;
}

pub trait ReadSession: Send {
    /// Admit and execute one graph read, transferring native ownership to the returned cursor.
    fn execute(
        self: Box<Self>,
        cypher: &str,
    ) -> std::result::Result<Box<dyn BatchReader>, BackendError>;
}

pub trait BatchReader: Send {
    fn schema(&self) -> &[ColumnSpec];

    /// Return at most `max_rows` rows, with an optional limit on the owned batch.
    /// `None` in the result means verified EOF.
    fn next_batch(
        &mut self,
        max_rows: usize,
        max_bytes: Option<usize>,
    ) -> std::result::Result<Option<Batch>, BackendError>;
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BackendError {
    Open,
    Admission,
    Execution,
    Schema,
    Arrow,
    BatchBudget,
    Timeout,
}

fn backend_error(error: BackendError) -> Error {
    let message = match error {
        BackendError::Open => "QW_OPEN: Could not open the configured Ladybug graph read-only",
        BackendError::Admission => {
            "QW_ADMISSION: Expected a single supported read-only Cypher graph query"
        }
        BackendError::Execution => "QW_EXECUTION: Ladybug could not execute the graph query",
        BackendError::Schema => {
            "QW_SCHEMA: Ladybug result does not match the declared scalar schema"
        }
        BackendError::Arrow => "QW_ARROW: Ladybug result batch could not be decoded",
        BackendError::BatchBudget => {
            "QW_BATCH_BUDGET: Ladybug result batch exceeds max_batch_bytes"
        }
        BackendError::Timeout => "QW_TIMEOUT: Ladybug graph query timed out",
    };
    Error::invalid_input(message)
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ScalarType {
    Boolean,
    BigInt,
    Double,
    Varchar,
}

impl ScalarType {
    fn logical_type(self, context: &Context) -> Result<LogicalType> {
        match self {
            Self::Boolean => bool::logical_type(context),
            Self::BigInt => i64::logical_type(context),
            Self::Double => f64::logical_type(context),
            Self::Varchar => String::logical_type(context),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ColumnSpec {
    pub name: String,
    pub data_type: ScalarType,
}

#[derive(Debug)]
pub enum ColumnData {
    Boolean(Vec<Option<bool>>),
    BigInt(Vec<Option<i64>>),
    Double(Vec<Option<f64>>),
    Varchar(Vec<Option<String>>),
}

impl ColumnData {
    fn layout(&self) -> (ScalarType, usize) {
        match self {
            Self::Boolean(rows) => (ScalarType::Boolean, rows.len()),
            Self::BigInt(rows) => (ScalarType::BigInt, rows.len()),
            Self::Double(rows) => (ScalarType::Double, rows.len()),
            Self::Varchar(rows) => (ScalarType::Varchar, rows.len()),
        }
    }

    fn write(&self, output: &mut DataChunk<'_>, index: usize) -> Result<()> {
        match self {
            Self::Boolean(rows) => {
                write_column::<bool>(output, index, rows.iter().map(Option::as_ref))
            }
            Self::BigInt(rows) => {
                write_column::<i64>(output, index, rows.iter().map(Option::as_ref))
            }
            Self::Double(rows) => {
                write_column::<f64>(output, index, rows.iter().map(Option::as_ref))
            }
            Self::Varchar(rows) => {
                write_column::<String>(output, index, rows.iter().map(Option::as_deref))
            }
        }
    }
}

#[derive(Debug)]
pub struct Batch {
    pub columns: Vec<ColumnData>,
    pub len: usize,
}

impl Batch {
    fn validate(&self, schema: &[ColumnSpec], capacity: usize) -> Result<()> {
        if self.len == 0
            || self.len > capacity
            || self.columns.len() != schema.len()
            || self
                .columns
                .iter()
                .zip(schema)
                .any(|(column, expected)| column.layout() != (expected.data_type, self.len))
        {
            return Err(backend_error(BackendError::Arrow));
        }
        Ok(())
    }
}

fn write_column<'a, T: WritableNativeElement>(
    output: &mut DataChunk<'_>,
    index: usize,
    rows: impl ExactSizeIterator<Item = Option<&'a T::Write>>,
) -> Result<()>
where
    T::Write: 'a,
{
    let mut vector = output.get_vector_at_mut::<T>(index)?;
    vector.set_size(rows.len())?;
    let mut writer = vector.writer()?;
    for (index, value) in rows.enumerate() {
        writer.set_option(index, value)?;
    }
    Ok(())
}

fn is_identifier(text: &str) -> bool {
    let mut bytes = text.bytes();
    bytes
        .next()
        .is_some_and(|byte| byte.is_ascii_alphabetic() || byte == b'_')
        && bytes.all(|byte| byte.is_ascii_alphanumeric() || byte == b'_')
}

fn parse_schema(schema: &str) -> Result<Vec<ColumnSpec>> {
    let invalid = || {
        Error::invalid_input(
            "QW_ARGUMENT: Expected comma-separated schema entries using BOOLEAN, BIGINT, DOUBLE or VARCHAR",
        )
    };
    let mut seen = HashSet::new();
    schema
        .split(',')
        .map(|entry| {
            let mut parts = entry.split_ascii_whitespace();
            let name = parts.next().ok_or_else(invalid)?;
            let type_name = parts.next().ok_or_else(invalid)?;
            if !is_identifier(name) || parts.next().is_some() {
                return Err(invalid());
            }
            if !seen.insert(name.to_ascii_lowercase()) {
                return Err(Error::invalid_input(
                    "QW_ARGUMENT: Duplicate result column in schema",
                ));
            }
            let data_type = match type_name.to_ascii_uppercase().as_str() {
                "BOOLEAN" => ScalarType::Boolean,
                "BIGINT" => ScalarType::BigInt,
                "DOUBLE" => ScalarType::Double,
                "VARCHAR" => ScalarType::Varchar,
                _ => return Err(invalid()),
            };
            Ok(ColumnSpec {
                name: name.to_owned(),
                data_type,
            })
        })
        .collect()
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ConfigInput {
    alias: String,
    path: String,
    timeout_ms: Option<u64>,
    max_batch_bytes: Option<usize>,
}

fn parse_config(text: &str) -> Result<ConfigInput> {
    let config: ConfigInput = serde_json::from_str(text).map_err(|_| {
        Error::invalid_input(
            "QW_CONFIG: Expected JSON with alias, path and optional timeout_ms and max_batch_bytes",
        )
    })?;
    if !is_identifier(&config.alias)
        || config.timeout_ms == Some(0)
        || config.max_batch_bytes == Some(0)
    {
        return Err(Error::invalid_input(
            "QW_CONFIG: Expected a valid alias and positive timeout_ms and max_batch_bytes",
        ));
    }
    Ok(config)
}

#[derive(Debug, Deserialize, Serialize)]
struct ConfigSnapshot {
    generation: u64,
    config: ConfigInput,
    #[serde(default)]
    catalog: Option<GraphCatalog>,
}

fn admit_local_path(context: &Context, path: &str) -> Result<String> {
    fn denied() -> Error {
        Error::invalid_input(
            "QW_ACCESS: The configured local Ladybug file requires DuckDB external access",
        )
    }

    let (enabled, _) = context
        .config()?
        .get_value("enable_external_access")
        .map_err(|_| denied())?;
    if bool::from_value(&enabled).map_err(|_| denied())? != Some(true) {
        return Err(denied());
    }
    let fs = FileSystem::new(context).map_err(|_| denied())?;
    if !Path::new(path).is_absolute()
        || path.contains('\0')
        || path.starts_with("//")
        || path.starts_with(r"\\")
        || fs.is_remote(path).map_err(|_| denied())?
    {
        return Err(denied());
    }
    let canonical = std::fs::canonicalize(path).map_err(|_| denied())?;
    let canonical = canonical.to_str().ok_or_else(denied)?;
    if !Path::new(canonical).is_file() {
        return Err(denied());
    }
    let probe = FileBuilder::new(&fs, canonical)
        .map_err(|_| denied())?
        .read()
        .open()
        .map_err(|_| denied())?;
    drop(probe);
    Ok(canonical.to_owned())
}

struct LadybugConfig<B>(Arc<B>);

impl<B: ReadBackend + 'static> CustomOptionCallbacks for LadybugConfig<B> {
    fn update(
        &self,
        context: &Context,
        value: Value,
        scope: SettingScope,
        is_reset: bool,
    ) -> Result<Value> {
        if matches!(scope, SettingScope::Session) {
            return Err(Error::invalid_input(
                "QW_CONFIG: Use SET GLOBAL for qw_ladybug_config",
            ));
        }
        if is_reset {
            return Option::<String>::None.value(context);
        }
        let text = String::from_value(&value)?.ok_or_else(|| {
            Error::invalid_input(
                "QW_CONFIG: Expected JSON with alias, path and optional timeout_ms and max_batch_bytes",
            )
        })?;
        let mut config = parse_config(&text)?;
        config.path = admit_local_path(context, &config.path)?;
        let generation = CONFIG_GENERATION
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
                value.checked_add(1)
            })
            .map_err(|_| Error::internal("QW_CONFIG: Configuration generation exhausted"))?;
        let catalog = self.0.catalog(Path::new(&config.path));
        let serialized = serde_json::to_string(&ConfigSnapshot {
            generation,
            config,
            catalog,
        })
        .map_err(|_| {
            Error::internal("QW_CONFIG: Could not store the validated graph configuration")
        })?;
        serialized.value(context)
    }
}

fn current_config(context: &Context) -> Result<ConfigSnapshot> {
    let (value, scope) = context.config()?.get_value(CONFIG)?;
    if matches!(scope, SettingScope::Session) {
        return Err(Error::invalid_input(
            "QW_CONFIG: Use SET GLOBAL for qw_ladybug_config",
        ));
    }
    let config = String::from_value(&value)?.ok_or_else(|| {
        Error::invalid_input(
            "QW_CONFIG: Configure an existing Ladybug graph with SET GLOBAL qw_ladybug_config",
        )
    })?;
    serde_json::from_str(&config)
        .map_err(|_| Error::invalid_input("QW_CONFIG: Invalid graph configuration"))
}

/// Validate a session graph selection against the provisioned name.
pub fn validate_graph_alias(context: &Context, alias: &str) -> Result<()> {
    if !current_config(context)?
        .config
        .alias
        .eq_ignore_ascii_case(alias)
    {
        return Err(Error::invalid_input(
            "QW_CONFIG: Unknown Ladybug graph alias",
        ));
    }
    Ok(())
}

struct BoundRead {
    config: ConfigSnapshot,
    cypher: String,
    schema: Vec<ColumnSpec>,
}

#[derive(Default)]
enum Scan {
    #[default]
    Dormant,
    Active(Box<dyn BatchReader>),
    Finished,
}

impl Scan {
    fn next(
        &mut self,
        expected: &[ColumnSpec],
        capacity: usize,
        max_batch_bytes: Option<usize>,
        start: impl FnOnce() -> Result<Box<dyn BatchReader>>,
    ) -> Result<Option<Batch>> {
        // Leave Finished on any failure or EOF; only a successful chunk keeps the cursor.
        let mut reader = match std::mem::replace(self, Self::Finished) {
            Self::Dormant => {
                let reader = start()?;
                let actual = reader.schema();
                if actual.len() != expected.len()
                    || actual.iter().zip(expected).any(|(actual, expected)| {
                        actual.data_type != expected.data_type
                            || !actual.name.eq_ignore_ascii_case(&expected.name)
                    })
                {
                    return Err(backend_error(BackendError::Schema));
                }
                reader
            }
            Self::Active(reader) => reader,
            Self::Finished => return Ok(None),
        };
        let Some(batch) = reader
            .next_batch(capacity, max_batch_bytes)
            .map_err(backend_error)?
        else {
            return Ok(None);
        };
        batch.validate(expected, capacity)?;
        *self = Self::Active(reader);
        Ok(Some(batch))
    }
}

enum GraphLanguage {
    Cypher,
    Gql,
}

impl GraphLanguage {
    fn parse(dialect: &str) -> Result<Self> {
        if dialect.eq_ignore_ascii_case("cypher") {
            Ok(Self::Cypher)
        } else if dialect.eq_ignore_ascii_case("gql") {
            Ok(Self::Gql)
        } else {
            Err(Error::invalid_input(
                "QW_ARGUMENT: Use the cypher or gql dialect",
            ))
        }
    }

    fn compile(self, query: String, parser: Option<GqlParser>) -> Result<String> {
        match self {
            Self::Cypher => Ok(query),
            Self::Gql => compile_gql_query(&query, parser),
        }
    }
}

struct GraphQuery<B> {
    backend: Arc<B>,
    inferred: bool,
    gql_parser: Option<GqlParser>,
}

impl<B: ReadBackend + 'static> TableFunctionCallbacks for GraphQuery<B> {
    type BindData = BoundRead;
    type LocalState = Scan;
    type GlobalState = ();

    fn bind(
        &self,
        context: &Context,
        args: BindArguments,
        handle: BindFunctionHandle<'_>,
    ) -> Result<BoundRead> {
        let required = |index| -> Result<String> {
            args.arg(index)?.resolved_value::<String>()?.flatten()
                .filter(|text| !text.trim().is_empty() && !text.contains('\0'))
                .ok_or_else(|| Error::invalid_input(
                    "QW_ARGUMENT: qw_query requires constant alias, dialect, query and schema values",
                ))
        };
        if self.inferred
            && args
                .arg(0)?
                .resolved_value::<String>()?
                .flatten()
                .is_none_or(|alias| alias.is_empty())
        {
            return Err(Error::invalid_input(
                "QW_CONFIG: Select a graph with SESSION SET GRAPH",
            ));
        }
        let alias = required(0)?;
        let dialect = required(1)?;
        let query = required(2)?;
        let declared = if self.inferred {
            None
        } else {
            Some(parse_schema(&required(3)?)?)
        };
        if !is_identifier(&alias) {
            return Err(Error::invalid_input(
                "QW_ARGUMENT: Use a configured graph alias",
            ));
        }
        let language = GraphLanguage::parse(&dialect)?;
        let config = current_config(context)?;
        if !config.config.alias.eq_ignore_ascii_case(&alias) {
            return Err(Error::invalid_input(
                "QW_CONFIG: Unknown Ladybug graph alias",
            ));
        }
        let cypher = match language {
            GraphLanguage::Gql if self.inferred => {
                self.backend.native_gql(query, self.gql_parser)?
            }
            _ => language.compile(query, self.gql_parser)?,
        };
        let schema = if let Some(declared) = declared {
            declared
        } else {
            let catalog = config.catalog.as_ref().ok_or_else(|| {
                Error::invalid_input(
                    "QW_SCHEMA: Ladybug catalog metadata unavailable for this graph generation",
                )
            })?;
            self.backend
                .projection(catalog, &cypher)
                .map_err(|err| match err {
                    BackendError::Schema => {
                        Error::invalid_input("QW_SCHEMA: Unknown or unsupported graph projection")
                    }
                    other => backend_error(other),
                })?
        };
        for column in &schema {
            handle.add_result_column(&column.name, &column.data_type.logical_type(context)?)?;
        }
        Ok(BoundRead {
            config,
            cypher,
            schema,
        })
    }

    fn init_local_state(
        &self,
        _: &Context,
        _: &BoundRead,
        _: Option<&()>,
        _: InitColumnData<'_>,
    ) -> Result<Option<Scan>> {
        Ok(Some(Scan::Dormant))
    }

    fn max_threads(
        &self,
        _: &Context,
        _: &BoundRead,
        _: Option<&()>,
        _: InitColumnData<'_>,
    ) -> Result<Option<NonZeroUsize>> {
        Ok(Some(NonZeroUsize::MIN))
    }

    fn exec(
        &self,
        context: &Context,
        bound: &BoundRead,
        scan: Option<&mut Scan>,
        _: Option<&()>,
        output: &mut DataChunk<'_>,
        _: ExecColumnInfo<'_>,
    ) -> Result<()> {
        let scan = scan.ok_or_else(|| Error::internal("qw_query: missing scan state"))?;
        let capacity = output.capacity()?;
        let Some(batch) = scan.next(
            &bound.schema,
            capacity,
            bound.config.config.max_batch_bytes,
            || {
                let current = current_config(context)?;
                if current.generation != bound.config.generation {
                    return Err(Error::invalid_input(
                        "QW_CONFIG: Ladybug configuration changed after binding",
                    ));
                }
                let path = admit_local_path(context, &bound.config.config.path)?;
                if path != bound.config.config.path {
                    return Err(Error::invalid_input(
                        "QW_ACCESS: Configured Ladybug path changed after binding",
                    ));
                }
                self.backend
                    .open(Path::new(&path), bound.config.config.timeout_ms)
                    .and_then(|session| session.execute(&bound.cypher))
                    .map_err(backend_error)
            },
        )?
        else {
            return Ok(());
        };
        for (index, column) in batch.columns.iter().enumerate() {
            if let Err(error) = column.write(output, index) {
                *scan = Scan::Finished;
                return Err(error);
            }
        }
        Ok(())
    }
}

/// Register the native graph query and its instance configuration for Cypher.
pub fn register(extension: &Extension, backend: impl ReadBackend + 'static) -> Result<()> {
    register_query(extension, backend, None)
}

/// Register the native graph query with a GQL parser in addition to Cypher.
pub fn register_with_gql(
    extension: &Extension,
    backend: impl ReadBackend + 'static,
    parser: GqlParser,
) -> Result<()> {
    register_query(extension, backend, Some(parser))
}

fn register_query(
    extension: &Extension,
    backend: impl ReadBackend + 'static,
    gql_parser: Option<GqlParser>,
) -> Result<()> {
    let backend = Arc::new(backend);
    CustomOptionBuilder::new(
        CONFIG,
        "JSON configuration for the embedded read-only Ladybug graph",
        String::logical_type(extension)?,
        LadybugConfig(Arc::clone(&backend)),
    )
    .default_value(Option::<String>::None.value(extension)?)
    .default_scope(SettingScope::Global)
    .register(extension)?;

    let description = if gql_parser.is_some() {
        "Read typed rows from an embedded Ladybug graph using read-only Cypher or a supported GQL subset."
    } else {
        "Read typed rows from one read-only Cypher query against an embedded Ladybug graph."
    };
    TableFunctionBuilder::new(
        "qw_query",
        SignatureBuilder::new()
            .param(FunctionParameter::new::<String>("alias"))
            .param(FunctionParameter::new::<String>("dialect"))
            .param(FunctionParameter::new::<String>("query"))
            .param(FunctionParameter::new::<String>("schema").kind(FunctionParameterKind::Named))
            .documentation(
                FunctionDocumentationBuilder::new()
                    .description(description)
                    .add_category("quack_weave"),
            ),
        GraphQuery {
            backend: Arc::clone(&backend),
            inferred: false,
            gql_parser,
        },
    )
    .register(extension)?;
    TableFunctionBuilder::new(
        "qw_graph_query",
        SignatureBuilder::new()
            .param(FunctionParameter::new::<String>("alias"))
            .param(FunctionParameter::new::<String>("dialect"))
            .param(FunctionParameter::new::<String>("query")),
        GraphQuery {
            backend,
            inferred: true,
            gql_parser,
        },
    )
    .register(extension)
}

#[cfg(test)]
mod tests;
