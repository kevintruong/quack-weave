//! Read-only graph results exposed as DuckDB table functions.

use std::{
    collections::{BTreeMap, HashSet},
    num::NonZeroUsize,
    path::Path,
    sync::{Arc, atomic::AtomicU64},
};

use duckdb_neo::{
    DuckDBType, FromValue, Result, ToValue,
    bind_arguments::BindArguments,
    connection::Context,
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

mod aggregate_scan;
mod gql;
mod graph_value;
pub use graph_value::{GraphColumn, GraphValue};
mod parameters;
mod providers;
use providers::{AliasReservations, GraphProvider, ProviderKind, resolve_alias};
mod runtime_watch;
use runtime_watch::{MAX_KEYS, RuntimeWatch};

pub use parameters::GraphParameter;

pub use gql::{GqlParser, compile_gql_query};

static CONFIG_GENERATION: AtomicU64 = AtomicU64::new(0);

/// Label and property names with their graph logical types, captured at registration.
pub type GraphCatalog = BTreeMap<String, Vec<(String, String)>>;

/// Resources prepared for a registration are published only after every
/// configuration, file identity and alias check succeeds.
pub struct PreparedRegistration<'a> {
    pub catalog: Option<GraphCatalog>,
    pub activate: Box<dyn FnOnce() + 'a>,
}

/// A backend that exclusively opens read-only database handles.
pub trait ReadBackend: Send + Sync {
    /// Read only catalog metadata while registering a graph generation.
    fn catalog(&self, _path: &Path) -> Option<GraphCatalog> {
        None
    }

    /// Open the admitted file read-only at registration and optionally capture its catalog.
    fn registration_catalog(
        &self,
        path: &Path,
        _declared: Option<&GraphCatalog>,
    ) -> std::result::Result<Option<GraphCatalog>, BackendError> {
        Ok(self.catalog(path))
    }

    fn prepare_registration<'a>(
        &'a self,
        path: &Path,
        declared: Option<&GraphCatalog>,
        generation: u64,
    ) -> std::result::Result<PreparedRegistration<'a>, BackendError> {
        Ok(PreparedRegistration {
            catalog: self.registration_catalog(path, declared)?,
            activate: Box::new(move || self.set_generation(Some(generation))),
        })
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

    /// Optional exact integer key filter issued by DuckDB's completed hash join.
    fn runtime_watch_keys(&self, _column: usize) -> Vec<i64> {
        Vec::new()
    }

    /// Publish the active registration after its metadata is captured. Readers that
    /// already own their sessions remain valid when the registration changes.
    fn set_generation(&self, _generation: Option<u64>) {}

    /// Open a scan for an admitted graph generation. Stateless backends can
    /// keep implementing only `open_projected` or `open`.
    fn open_for_generation(
        &self,
        path: &Path,
        timeout_ms: Option<u64>,
        schema: &[ColumnSpec],
        _generation: &GraphGeneration,
    ) -> std::result::Result<Box<dyn ReadSession>, BackendError> {
        self.open_projected(path, timeout_ms, schema)
    }

    fn open_projected(
        &self,
        path: &Path,
        timeout_ms: Option<u64>,
        _schema: &[ColumnSpec],
    ) -> std::result::Result<Box<dyn ReadSession>, BackendError> {
        self.open(path, timeout_ms)
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
    ) -> std::result::Result<Box<dyn BatchReader>, BackendError> {
        self.execute_with_params(cypher, &[])
    }

    fn execute_with_params(
        self: Box<Self>,
        cypher: &str,
        params: &[(String, GraphParameter)],
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
        BackendError::Open => "QW_OPEN: Could not open the configured graph read-only",
        BackendError::Admission => {
            "QW_ADMISSION: Expected a single supported read-only Cypher graph query"
        }
        BackendError::Execution => "QW_EXECUTION: The provider could not execute the graph query",
        BackendError::Schema => "QW_SCHEMA: Graph result does not match the declared scalar schema",
        BackendError::Arrow => "QW_ARROW: Graph result batch could not be decoded",
        BackendError::BatchBudget => "QW_BATCH_BUDGET: Graph result batch exceeds max_batch_bytes",
        BackendError::Timeout => "QW_TIMEOUT: Graph query timed out",
    };
    Error::invalid_input(message)
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ScalarType {
    Boolean,
    BigInt,
    Double,
    Varchar,
    Struct(Vec<ColumnSpec>),
    List(Box<ScalarType>),
}

impl ScalarType {
    fn logical_type(&self, context: &Context) -> Result<LogicalType> {
        match self {
            Self::Boolean => bool::logical_type(context),
            Self::BigInt => i64::logical_type(context),
            Self::Double => f64::logical_type(context),
            Self::Varchar => String::logical_type(context),
            Self::Struct(_) | Self::List(_) => self.nested_type(context),
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
    Graph(Box<GraphColumn>),
}

impl ColumnData {
    fn layout(&self) -> (&ScalarType, usize) {
        match self {
            Self::Boolean(rows) => (&ScalarType::Boolean, rows.len()),
            Self::BigInt(rows) => (&ScalarType::BigInt, rows.len()),
            Self::Double(rows) => (&ScalarType::Double, rows.len()),
            Self::Varchar(rows) => (&ScalarType::Varchar, rows.len()),
            Self::Graph(col) => (col.ty.as_ref(), col.rows.len()),
        }
    }

    fn write(&self, context: &Context, output: &mut DataChunk<'_>, index: usize) -> Result<()> {
        match self {
            Self::Graph(col) => col.write(context, output, index),
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
                .any(|(column, expected)| column.layout() != (&expected.data_type, self.len))
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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    catalog: Option<BTreeMap<String, BTreeMap<String, String>>>,
}

fn parse_config(text: &str) -> Result<ConfigInput> {
    let config: ConfigInput = serde_json::from_str(text).map_err(|_| {
        Error::invalid_input("QW_CONFIG: Expected a graph configuration object with alias and path")
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

/// Identity captured together with read-only catalog metadata during registration.
#[derive(Debug, PartialEq, Deserialize, Serialize)]
pub struct GraphGeneration {
    id: u64,
    length: u64,
    modified_ns: i128,
    #[cfg(unix)]
    device_inode: (u64, u64),
}

impl GraphGeneration {
    pub fn id(&self) -> u64 {
        self.id
    }

    pub fn capture(id: u64, path: &Path) -> Result<Self> {
        let metadata = std::fs::metadata(path)
            .map_err(|_| Error::invalid_input("QW_ACCESS: Graph file unavailable"))?;
        let modified = metadata
            .modified()
            .map_err(|_| Error::invalid_input("QW_ACCESS: Graph timestamp unavailable"))?;
        // SystemTime's serde encoding excludes pre-epoch files. Duration's u64
        // seconds and nanoseconds fit in i128 on either side of the epoch.
        let modified_ns = match modified.duration_since(std::time::UNIX_EPOCH) {
            Ok(after) => after.as_nanos() as i128,
            Err(before) => -(before.duration().as_nanos() as i128),
        };
        Ok(Self {
            id,
            length: metadata.len(),
            modified_ns,
            #[cfg(unix)]
            device_inode: {
                use std::os::unix::fs::MetadataExt;
                (metadata.dev(), metadata.ino())
            },
        })
    }

    pub fn validate(&self, path: &Path) -> Result<()> {
        if self != &Self::capture(self.id, path)? {
            return Err(Error::invalid_input(
                "QW_OPEN: Graph file changed; register it again",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Deserialize, Serialize)]
struct ConfigSnapshot {
    generation: GraphGeneration,
    config: ConfigInput,
    #[serde(default)]
    catalog: Option<GraphCatalog>,
}

fn admit_local_path(context: &Context, path: &str) -> Result<String> {
    fn denied() -> Error {
        Error::invalid_input(
            "QW_ACCESS: The configured local graph file requires DuckDB external access",
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

/// Validate a session graph selection against this instance's provisioned names.
pub fn validate_graph_alias(context: &Context, alias: &str) -> Result<()> {
    resolve_alias(
        context,
        alias,
        [ProviderKind::Ladybug, ProviderKind::Relate],
    )
    .map(|_| ())
}

struct BoundRead {
    provider: GraphProvider,
    watch: Option<RuntimeWatch>,
    params: Vec<(String, GraphParameter)>,
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

#[derive(Clone, Copy, PartialEq, Eq)]
enum GraphQueryKind {
    DeclaredSchema,
    InferredSchema,
    Parameterized,
    Filtered,
    RuntimeWatch,
}

struct GraphQuery {
    providers: Arc<[GraphProvider]>,
    kind: GraphQueryKind,
    gql_parser: Option<GqlParser>,
}

impl TableFunctionCallbacks for GraphQuery {
    type BindData = BoundRead;
    type LocalState = (Scan, Option<String>);
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
        if self.kind != GraphQueryKind::DeclaredSchema
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
        let mut query = required(2)?;
        let declared = if self.kind != GraphQueryKind::DeclaredSchema {
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
        let (index, config) = resolve_alias(
            context,
            &alias,
            self.providers.iter().map(|provider| provider.kind),
        )?;
        let provider = &self.providers[index];
        let backend = &provider.backend;
        let mut watch = None;
        if provider.kind == ProviderKind::Ladybug
            && matches!(
                self.kind,
                GraphQueryKind::Filtered | GraphQueryKind::RuntimeWatch
            )
        {
            let label = required(3)?;
            let property = required(4)?;
            if config
                .catalog
                .as_ref()
                .and_then(|c| c.get(&label))
                .is_some_and(|properties| {
                    properties
                        .iter()
                        .any(|(name, ty)| name == &property && ty == "INT64")
                })
            {
                if self.kind == GraphQueryKind::RuntimeWatch {
                    let var = required(5)?;
                    let column = required(6)?;
                    watch = RuntimeWatch::from_scan(&query, &label, &property, &var, &column);
                    if watch.is_some() {
                        // The default estimate is one row. Give bounded watchlists an
                        // opportunity to build the hash table when graph size is unknown.
                        handle.set_cardinality(MAX_KEYS + 1, false)?;
                    }
                } else {
                    query = required(5)?;
                }
            }
        }
        let cypher = match language {
            GraphLanguage::Gql if self.kind != GraphQueryKind::DeclaredSchema => {
                backend.native_gql(query, self.gql_parser)?
            }
            _ => language.compile(query, self.gql_parser)?,
        };
        let schema = if let Some(declared) = declared {
            declared
        } else {
            let catalog = config.catalog.as_ref().ok_or_else(|| {
                Error::invalid_input(
                    "QW_SCHEMA: Catalog metadata unavailable for this graph generation",
                )
            })?;
            backend
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
        let params = if self.kind == GraphQueryKind::Parameterized {
            parameters::from_struct(
                context,
                &args.arg(3)?.value()?.ok_or_else(|| {
                    Error::invalid_input("QW_ARGUMENT: Expected bound graph parameter values")
                })?,
            )?
        } else {
            Vec::new()
        };
        Ok(BoundRead {
            provider: provider.clone(),
            watch,
            params,
            config,
            cypher,
            schema,
        })
    }

    fn init_local_state(
        &self,
        _: &Context,
        bound: &BoundRead,
        _: Option<&()>,
        _: InitColumnData<'_>,
    ) -> Result<Option<Self::LocalState>> {
        let filtered = bound.watch.as_ref().and_then(|watch| {
            watch.query(&bound.provider.backend.runtime_watch_keys(watch.column))
        });
        Ok(Some((Scan::Dormant, filtered)))
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
        scan: Option<&mut Self::LocalState>,
        _: Option<&()>,
        output: &mut DataChunk<'_>,
        _: ExecColumnInfo<'_>,
    ) -> Result<()> {
        let (scan, filtered) =
            scan.ok_or_else(|| Error::internal("qw_query: missing scan state"))?;
        let capacity = output.capacity()?;
        let Some(batch) = scan.next(
            &bound.schema,
            capacity,
            bound.config.config.max_batch_bytes,
            || {
                let current = bound.provider.kind.config(context)?;
                if current.is_none_or(|c| c.generation.id != bound.config.generation.id) {
                    return Err(Error::invalid_input(format!(
                        "QW_CONFIG: {} configuration changed after binding",
                        bound.provider.kind.name()
                    )));
                }
                if self.providers.len() > 1 {
                    bound
                        .provider
                        .kind
                        .check_sibling(context, &bound.config.config.alias)?;
                }
                let path = admit_local_path(context, &bound.config.config.path)?;
                if path != bound.config.config.path {
                    return Err(Error::invalid_input(format!(
                        "QW_ACCESS: Configured {} path changed after binding",
                        bound.provider.kind.name()
                    )));
                }
                bound.config.generation.validate(Path::new(&path))?;
                let session = bound
                    .provider
                    .backend
                    .open_for_generation(
                        Path::new(&path),
                        bound.config.config.timeout_ms,
                        &bound.schema,
                        &bound.config.generation,
                    )
                    .map_err(backend_error)?;
                bound.config.generation.validate(Path::new(&path))?;
                session
                    .execute_with_params(
                        filtered.as_deref().unwrap_or(&bound.cypher),
                        &bound.params,
                    )
                    .map_err(backend_error)
            },
        )?
        else {
            return Ok(());
        };
        for (index, column) in batch.columns.iter().enumerate() {
            if let Err(error) = column.write(context, output, index) {
                *scan = Scan::Finished;
                return Err(error);
            }
        }
        Ok(())
    }
}

/// Register the native graph query and its instance configuration for Cypher.
pub fn register(extension: &Extension, backend: impl ReadBackend + 'static) -> Result<()> {
    register_query(
        extension,
        vec![GraphProvider::new(ProviderKind::Ladybug, backend)],
        None,
    )
}

/// Register the native graph query with a GQL parser in addition to Cypher.
pub fn register_with_gql(
    extension: &Extension,
    backend: impl ReadBackend + 'static,
    parser: GqlParser,
) -> Result<()> {
    register_query(
        extension,
        vec![GraphProvider::new(ProviderKind::Ladybug, backend)],
        Some(parser),
    )
}

/// Install both real providers behind the same public Cypher, GQL and SQL/PGQ entry points.
pub fn register_with_relate(
    extension: &Extension,
    ladybug: impl ReadBackend + 'static,
    relate: impl ReadBackend + 'static,
    parser: GqlParser,
) -> Result<()> {
    register_query(
        extension,
        vec![
            GraphProvider::new(ProviderKind::Ladybug, ladybug),
            GraphProvider::new(ProviderKind::Relate, relate),
        ],
        Some(parser),
    )
}

fn register_query(
    extension: &Extension,
    providers: Vec<GraphProvider>,
    gql_parser: Option<GqlParser>,
) -> Result<()> {
    let providers: Arc<[GraphProvider]> = providers.into();
    let aliases = (providers.len() > 1).then(|| Arc::new(AliasReservations::default()));
    for provider in providers.iter() {
        provider.register_option(extension, aliases.clone())?;
    }

    let description = if gql_parser.is_some() {
        "Read typed rows from a configured graph using read-only Cypher or a supported GQL subset."
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
            providers: Arc::clone(&providers),
            kind: GraphQueryKind::DeclaredSchema,
            gql_parser,
        },
    )
    .with_get_bind_info()
    .register(extension)?;
    for (name, kind) in [
        ("qw_graph_query", GraphQueryKind::InferredSchema),
        ("qw_graph_query_params", GraphQueryKind::Parameterized),
        ("qw_graph_query_filtered", GraphQueryKind::Filtered),
        ("qw_graph_query_watch", GraphQueryKind::RuntimeWatch),
    ] {
        let mut signature = SignatureBuilder::new()
            .param(FunctionParameter::new::<String>("alias"))
            .param(FunctionParameter::new::<String>("dialect"))
            .param(FunctionParameter::new::<String>("query"));
        if kind == GraphQueryKind::Filtered {
            for arg in ["label", "property", "candidate"] {
                signature = signature.param(FunctionParameter::new::<String>(arg));
            }
        }
        if kind == GraphQueryKind::RuntimeWatch {
            for arg in ["label", "property", "variable", "column"] {
                signature = signature.param(FunctionParameter::new::<String>(arg));
            }
        }
        if kind == GraphQueryKind::Parameterized {
            signature =
                signature.param(FunctionParameter::new::<duckdb_neo::types::Any>("bindings"));
        }
        TableFunctionBuilder::new(
            name,
            signature,
            GraphQuery {
                providers: Arc::clone(&providers),
                kind,
                gql_parser,
            },
        )
        .with_get_bind_info()
        .register(extension)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests;
