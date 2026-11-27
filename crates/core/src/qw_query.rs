//! Read-only graph results exposed as DuckDB table functions.

use std::{
    collections::BTreeMap,
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
    log::{Log, LogLevel},
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
mod cloud;
pub use cloud::{CloudSource, CloudStorage};
mod filters;
mod fragment;
use fragment::GraphFragment;
mod gql;
mod graph_value;
pub use graph_value::{GraphColumn, GraphValue};
mod parameters;
mod projection;
mod route_feedback;
use projection::ScanProjection;
mod providers;
pub use providers::{
    GraphProvider, ProviderDescriptor, ProviderRegistry, ProviderRewrite, ProviderSource,
};
mod remote;
pub use remote::{RemoteCredential, RemoteSource, ScanLimits};
mod schema;
use schema::is_identifier;
pub use schema::{ColumnSpec, ScalarType};
mod runtime_watch;
use runtime_watch::{MAX_KEYS, RuntimeWatch};

pub use parameters::GraphParameter;

pub use gql::{GqlParser, compile_gql_query};

static CONFIG_GENERATION: AtomicU64 = AtomicU64::new(0);

/// Label and property names with their graph logical types, captured at registration.
pub type GraphCatalog = BTreeMap<String, Vec<(String, String)>>;

type DeclaredCatalog = BTreeMap<String, BTreeMap<String, String>>;

/// Registration-time input sizes for DuckDB's cost model. A labeled match
/// can emit fewer rows than its storage table or its provider-wide population.
#[derive(Debug, Deserialize, Serialize)]
pub enum GraphPopulations {
    ByTable(BTreeMap<String, u64>),
    ByEntity { nodes: u64, edges: u64 },
}

/// A retired native resource to drop outside the registry mutex.
pub type RetiredRegistration = Box<dyn Send>;

/// Resources prepared for a registration are published only after every
/// configuration, file identity and alias check succeeds.
pub struct PreparedRegistration<'a> {
    pub catalog: Option<GraphCatalog>,
    pub single_pattern_row_bound: Option<u64>,
    pub populations: Option<GraphPopulations>,
    pub activate: Box<dyn FnOnce() -> Option<RetiredRegistration> + 'a>,
}

/// A host proof for a bounded graph prefix on an exact execution-local join.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct OrderedWatchlistLimit {
    pub order_column: usize,
    pub join_column: usize,
    pub limit: u64,
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
            single_pattern_row_bound: None,
            populations: None,
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

    fn native_gql(&self, query: String, parser: GqlParser) -> Result<String> {
        compile_gql_query(&query, parser)
    }

    /// Optional exact integer key filter issued by DuckDB's completed hash join.
    fn runtime_watch_keys(&self, _column: usize) -> Vec<i64> {
        Vec::new()
    }

    /// Plan-local offer for providers that implement a native ordered prefix.
    fn ordered_watchlist_limit(&self) -> Option<OrderedWatchlistLimit> {
        None
    }

    /// Translate the ordered prefix with DuckDB's ASC NULLS LAST semantics.
    fn ordered_watchlist_suffix(&self, _order_column: usize, _limit: u64) -> Option<String> {
        None
    }

    /// Swap the active native cache owner without opening or dropping resources.
    /// Readers that already own their sessions remain valid across registration changes.
    fn set_generation(&self, _generation: Option<u64>) -> Option<RetiredRegistration> {
        None
    }

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
        _path: &Path,
        _timeout_ms: Option<u64>,
    ) -> std::result::Result<Box<dyn ReadSession>, BackendError> {
        Err(BackendError::Open)
    }

    /// Check the connector-specific endpoint and credential reference without network I/O.
    fn validate_remote(&self, _source: &RemoteSource) -> std::result::Result<(), BackendError> {
        Err(BackendError::RemoteConfig)
    }

    /// Construct the session with the executing connection's context.
    /// Submit the remote read only in `execute_with_params`.
    fn open_remote(
        &self,
        _context: &Context,
        _source: &RemoteSource,
        _limits: &ScanLimits,
        _schema: &[ColumnSpec],
    ) -> std::result::Result<Box<dyn ReadSession>, BackendError> {
        Err(BackendError::Open)
    }

    /// Whether the packaged engine can attach this object store read-only.
    fn supports_cloud_storage(&self, _storage: CloudStorage) -> bool {
        false
    }

    /// Attach with the registration connection's credentials and capture metadata.
    fn cloud_catalog(
        &self,
        _context: &Context,
        _source: &CloudSource,
        _timeout_ms: Option<u64>,
    ) -> std::result::Result<GraphCatalog, BackendError> {
        Err(BackendError::RemoteConfig)
    }

    /// Resolve the executing connection's credential without contacting storage.
    /// The returned session performs ATTACH after admission in execute_with_params.
    fn open_cloud(
        &self,
        _context: &Context,
        _source: &CloudSource,
        _timeout_ms: Option<u64>,
        _schema: &[ColumnSpec],
    ) -> std::result::Result<Box<dyn ReadSession>, BackendError> {
        Err(BackendError::Open)
    }
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
    RemoteConfig,
    RemoteAuth,
    RemoteTransport,
    ResponseBudget,
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
        BackendError::RemoteConfig => "QW_CONFIG: Invalid or unapproved remote graph endpoint",
        BackendError::RemoteAuth => "QW_AUTH: Remote graph credentials unavailable or rejected",
        BackendError::RemoteTransport => "QW_TRANSPORT: Remote graph request failed",
        BackendError::ResponseBudget => {
            "QW_RESPONSE_BUDGET: Remote graph response exceeds max_response_bytes"
        }
    };
    Error::invalid_input(message)
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

fn parse_schema(schema: &str) -> Result<Vec<ColumnSpec>> {
    schema::parse_schema(schema).map_err(Error::invalid_input)
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ConfigInput {
    alias: String,
    path: String,
    timeout_ms: Option<u64>,
    max_batch_bytes: Option<usize>,
    #[serde(
        default,
        deserialize_with = "remote::present_reference",
        skip_serializing_if = "Option::is_none"
    )]
    secret: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    catalog: Option<DeclaredCatalog>,
}

impl ConfigInput {
    fn has_resource_limit(&self) -> bool {
        self.timeout_ms.is_some() || self.max_batch_bytes.is_some()
    }
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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    length: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    modified_ns: Option<i128>,
    #[cfg(unix)]
    #[serde(default, skip_serializing_if = "Option::is_none")]
    device_inode: Option<(u64, u64)>,
}

impl GraphGeneration {
    pub fn id(&self) -> u64 {
        self.id
    }

    fn remote(id: u64) -> Self {
        Self {
            id,
            length: None,
            modified_ns: None,
            #[cfg(unix)]
            device_inode: None,
        }
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
            length: Some(metadata.len()),
            modified_ns: Some(modified_ns),
            #[cfg(unix)]
            device_inode: {
                use std::os::unix::fs::MetadataExt;
                Some((metadata.dev(), metadata.ino()))
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
#[serde(untagged)]
enum RegisteredConfig {
    Local(ConfigInput),
    Remote(remote::RemoteConfig),
    Cloud(cloud::CloudConfig),
}

impl RegisteredConfig {
    fn alias(&self) -> &str {
        match self {
            Self::Local(config) => &config.alias,
            Self::Remote(config) => &config.alias,
            Self::Cloud(config) => &config.alias,
        }
    }

    fn max_batch_bytes(&self) -> Option<usize> {
        match self {
            Self::Local(config) => config.max_batch_bytes,
            Self::Remote(config) => config.max_batch_bytes,
            Self::Cloud(config) => config.max_batch_bytes,
        }
    }

    fn has_resource_limit(&self) -> bool {
        match self {
            Self::Local(config) => config.has_resource_limit(),
            Self::Remote(_) => true,
            Self::Cloud(config) => config.timeout_ms.is_some() || config.max_batch_bytes.is_some(),
        }
    }

    fn allows_rewrites(&self) -> bool {
        matches!(self, Self::Local(config) if !config.has_resource_limit())
    }
}

#[derive(Debug, Deserialize, Serialize)]
struct ConfigSnapshot {
    generation: GraphGeneration,
    config: RegisteredConfig,
    #[serde(default)]
    catalog: Option<GraphCatalog>,
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    observed_catalog: bool,
    #[serde(default)]
    single_pattern_row_bound: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    populations: Option<GraphPopulations>,
    #[serde(skip)]
    feedback: route_feedback::Feedback,
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

struct BoundRead {
    static_predicate: std::sync::Mutex<Option<String>>,
    fragment: Option<GraphFragment>,
    provider: GraphProvider,
    literal_candidate: Option<String>,
    watch: Option<RuntimeWatch>,
    params: Vec<(String, GraphParameter)>,
    config: Arc<ConfigSnapshot>,
    cypher: String,
    schema: Vec<ColumnSpec>,
}

impl BoundRead {
    fn allows_pgq_rewrite(&self) -> bool {
        self.fragment.is_some()
            && self.literal_candidate.is_none()
            && self.config.config.allows_rewrites()
            && match self.provider.descriptor.rewrite {
                ProviderRewrite::Disabled => false,
                ProviderRewrite::LabelCatalog => true,
                ProviderRewrite::ObservedCatalog => self.config.observed_catalog,
            }
    }
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

    fn compile(&self, query: String, parser: GqlParser) -> Result<String> {
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
    providers: ProviderRegistry,
    kind: GraphQueryKind,
    gql_parser: GqlParser,
}

impl TableFunctionCallbacks for GraphQuery {
    type BindData = BoundRead;
    type LocalState = (Scan, ScanProjection);
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
        let query = required(2)?;
        let fragment = match args.arg_by_name("pgq")? {
            Some(arg) => arg
                .resolved_value::<String>()?
                .flatten()
                .map(|wire| {
                    if dialect.eq_ignore_ascii_case("cypher")
                        && let Some(fragment) = GraphFragment::bind(&wire, &query)
                    {
                        return Ok(fragment);
                    }
                    Err(Error::invalid_input(
                        "QW_ARGUMENT: Invalid structured graph fragment",
                    ))
                })
                .transpose()?,
            None => None,
        };
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
        let (provider, config) = self.providers.resolve_alias(&alias)?;
        let remote = provider.descriptor.source == ProviderSource::RemoteEndpoint;
        if remote
            && (!matches!(language, GraphLanguage::Cypher)
                || self.kind != GraphQueryKind::DeclaredSchema && fragment.is_none())
        {
            return Err(Error::invalid_input(
                "QW_ARGUMENT: Remote graph reads require GRAPH_TABLE or qw_query with an explicit Cypher schema",
            ));
        }
        let backend = &provider.backend;
        let mut watch = None;
        let mut literal_candidate = None;
        if provider.descriptor.rewrite == ProviderRewrite::LabelCatalog
            && matches!(config.config, RegisteredConfig::Local(_))
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
                    if !config.config.has_resource_limit() {
                        watch = RuntimeWatch::from_scan(&query, &label, &property, &var, &column);
                    }
                } else {
                    let candidate = required(5)?;
                    if !config.config.has_resource_limit()
                        && runtime_watch::filtered_column(&query, &candidate, &label, &property)
                            .is_some()
                    {
                        literal_candidate = Some(candidate);
                    }
                }
            }
        }
        let compile = |query| match language {
            GraphLanguage::Gql if self.kind != GraphQueryKind::DeclaredSchema => {
                backend.native_gql(query, self.gql_parser)
            }
            _ => language.compile(query, self.gql_parser),
        };
        let cypher = compile(query)?;
        let mut literal_candidate = literal_candidate.map(compile).transpose()?;
        let schema = if let Some(declared) = declared {
            declared
        } else {
            let catalog = config.catalog.as_ref().ok_or_else(|| {
                Error::invalid_input(
                    "QW_SCHEMA: Catalog metadata unavailable for this graph generation",
                )
            })?;
            let projection = if remote {
                fragment
                    .as_ref()
                    .ok_or(BackendError::Schema)
                    .and_then(|fragment| fragment.declared_projection(catalog))
            } else {
                backend.projection(catalog, &cypher)
            };
            projection.map_err(|err| match err {
                BackendError::Schema => {
                    Error::invalid_input("QW_SCHEMA: Unknown or unsupported graph projection")
                }
                other => backend_error(other),
            })?
        };
        // A Relate declaration can claim BIGINT for a stored string. Pushing the
        // filter could hide a conversion error. Only its observed, kind-qualified
        // catalog certifies the actual graph values. Keep explicit budgets on the
        // original scan so changing the row count cannot suppress a budget error.
        if provider.descriptor.rewrite == ProviderRewrite::ObservedCatalog
            && matches!(
                self.kind,
                GraphQueryKind::Filtered | GraphQueryKind::RuntimeWatch
            )
            && config.config.allows_rewrites()
            && config.observed_catalog
        {
            let label = required(3)?;
            let property = required(4)?;
            let is_integer = |i: usize| {
                schema
                    .get(i)
                    .is_some_and(|c| c.data_type == ScalarType::BigInt)
            };
            if self.kind == GraphQueryKind::RuntimeWatch {
                watch = RuntimeWatch::from_scan(
                    &cypher,
                    &label,
                    &property,
                    &required(5)?,
                    &required(6)?,
                )
                .filter(|w| is_integer(w.column));
            } else {
                let candidate = required(5)?;
                if runtime_watch::filtered_column(&cypher, &candidate, &label, &property)
                    .is_some_and(is_integer)
                {
                    literal_candidate = Some(candidate);
                }
            }
        }
        if let Some(rows) = fragment
            .as_ref()
            .and_then(|f| f.estimate(config.populations.as_ref()?))
        {
            handle.set_cardinality(rows.try_into().unwrap_or(usize::MAX), false)?;
        }
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
        } else if let Some(arg) = args.arg_by_name("bindings")? {
            let bindings = arg.value()?.ok_or_else(|| {
                Error::invalid_input("QW_ARGUMENT: Expected bound graph parameter values")
            })?;
            if bindings.is_null()? {
                Vec::new()
            } else {
                parameters::from_struct(context, &bindings)?
            }
        } else {
            Vec::new()
        };
        Ok(BoundRead {
            static_predicate: Default::default(),
            fragment,
            provider: provider.clone(),
            literal_candidate,
            watch,
            params,
            config,
            cypher,
            schema,
        })
    }

    fn init_local_state(
        &self,
        context: &Context,
        bound: &BoundRead,
        _: Option<&()>,
        columns: InitColumnData<'_>,
    ) -> Result<Option<Self::LocalState>> {
        Ok(Some((
            Scan::Dormant,
            ScanProjection::new(context, bound, columns)?,
        )))
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
        let (scan, projection) =
            scan.ok_or_else(|| Error::internal("qw_query: missing scan state"))?;
        let capacity = output.capacity()?;
        // Time active provider/bridge work only, excluding the intervals between
        // DuckDB pulls and output materialization.
        let started = projection
            .feedback
            .as_ref()
            .map(|_| std::time::Instant::now());
        let next = scan.next(
            projection.schema(bound),
            capacity,
            bound.config.config.max_batch_bytes(),
            || {
                let provider = bound.provider.descriptor;
                let generation = &bound.config.generation;
                self.providers
                    .require_generation(provider, generation.id())?;
                let session = match &bound.config.config {
                    RegisteredConfig::Local(config) => {
                        let path = admit_local_path(context, &config.path)?;
                        if path != config.path {
                            return Err(Error::invalid_input(format!(
                                "QW_ACCESS: Configured {} path changed after binding",
                                provider.name
                            )));
                        }
                        let path = Path::new(&path);
                        self.providers
                            .open_admitted(provider, generation.id(), || {
                                generation.validate(path)?;
                                let session = bound
                                    .provider
                                    .backend
                                    .open_for_generation(
                                        path,
                                        config.timeout_ms,
                                        projection.schema(bound),
                                        generation,
                                    )
                                    .map_err(backend_error)?;
                                generation.validate(path)?;
                                Ok(session)
                            })?
                    }
                    RegisteredConfig::Remote(config) => {
                        remote::admit_remote(context)?;
                        let session = bound
                            .provider
                            .backend
                            .open_remote(
                                context,
                                &config.source(),
                                &config.limits(),
                                projection.schema(bound),
                            )
                            .map_err(backend_error)?;
                        remote::admit_remote(context)?;
                        // Remote session construction performs no graph read. This
                        // last generation check admits the request before submission.
                        self.providers
                            .require_generation(provider, generation.id())?;
                        session
                    }
                    RegisteredConfig::Cloud(config) => {
                        remote::admit_remote(context)?;
                        let session = bound
                            .provider
                            .backend
                            .open_cloud(
                                context,
                                &config.source,
                                config.timeout_ms,
                                projection.schema(bound),
                            )
                            .map_err(backend_error)?;
                        remote::admit_remote(context)?;
                        self.providers
                            .require_generation(provider, generation.id())?;
                        session
                    }
                };
                // The provider session is open for this generation. Diagnostics
                // and query execution happen after releasing the publication gate.
                let _ = Log::log_on_context(
                    context,
                    LogLevel::Info,
                    &generation.id().to_string(),
                    "QuackWeaveGraphAdmission",
                );
                let reader = session
                    .execute_with_params(projection.query(bound), &bound.params)
                    .map_err(backend_error)?;
                if bound.fragment.is_some()
                    || bound.watch.is_some()
                    || bound.literal_candidate.is_some()
                {
                    projection.watchlist_route.log(context);
                }
                Ok(reader)
            },
        );
        if let (Some(started), Some(observation)) = (started, projection.feedback.as_mut()) {
            observation.elapsed += started.elapsed();
        }
        let next = match next {
            Ok(next) => next,
            Err(error) => {
                projection.feedback = None;
                return Err(error);
            }
        };
        let Some(batch) = next else {
            if let Some(observation) = projection.feedback.take()
                && self
                    .providers
                    .check_generation(bound.provider.descriptor.id, bound.config.generation.id())
                    .unwrap_or(false)
            {
                observation.finish(&bound.config.feedback, context);
            }
            return Ok(());
        };
        for (index, &provider_column) in projection.output_columns.iter().enumerate() {
            if let Err(error) = batch.columns[provider_column].write(context, output, index) {
                *scan = Scan::Finished;
                projection.feedback = None;
                return Err(error);
            }
        }
        Ok(())
    }
}

/// Install the graph queries and settings for the providers enabled by the native extension.
pub fn register_query(
    extension: &Extension,
    providers: Vec<GraphProvider>,
    gql_parser: GqlParser,
) -> Result<ProviderRegistry> {
    let providers = ProviderRegistry::new(providers)?;
    remote::register(extension)?;
    runtime_watch::register(extension)?;
    route_feedback::register(extension)?;
    providers.register_options(extension)?;
    TableFunctionBuilder::new(
        "qw_graph_providers",
        SignatureBuilder::new().documentation(
            FunctionDocumentationBuilder::new()
                .description("List enabled graph providers and their configuration settings.")
                .add_category("quack_weave"),
        ),
        providers.clone(),
    )
    .register(extension)?;

    TableFunctionBuilder::new(
        "qw_query",
        SignatureBuilder::new()
            .param(FunctionParameter::new::<String>("alias"))
            .param(FunctionParameter::new::<String>("dialect"))
            .param(FunctionParameter::new::<String>("query"))
            .param(FunctionParameter::new::<String>("schema").kind(FunctionParameterKind::Named))
            .param(
                FunctionParameter::new::<duckdb_neo::types::Any>("bindings")
                    .default_value(Option::<String>::None)
                    .kind(FunctionParameterKind::Named),
            )
            .documentation(
                FunctionDocumentationBuilder::new()
                    .description("Read typed rows from a configured graph using read-only Cypher or a supported GQL subset.")
                    .add_category("quack_weave"),
            ),
        GraphQuery {
            providers: providers.clone(),
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
        if kind != GraphQueryKind::Parameterized {
            signature = signature.param(
                FunctionParameter::with_default("pgq", Option::<String>::None)
                    .kind(FunctionParameterKind::Named),
            );
        }
        TableFunctionBuilder::new(
            name,
            signature,
            GraphQuery {
                providers: providers.clone(),
                kind,
                gql_parser,
            },
        )
        .with_get_bind_info()
        .with_filter_pushdown()
        .with_projection_pushdown(true)
        .register(extension)?;
    }
    Ok(providers)
}

impl TableFunctionCallbacks for ProviderRegistry {
    type BindData = ();
    type GlobalState = ();
    type LocalState = (Vec<Option<String>>, usize);

    fn bind(
        &self,
        context: &Context,
        _: BindArguments,
        handle: BindFunctionHandle<'_>,
    ) -> Result<()> {
        let text = String::logical_type(context)?;
        handle.add_result_column("provider_id", &text)?;
        handle.add_result_column("setting_name", &text)?;
        handle.add_result_column("active_alias", &text)?;
        handle.set_cardinality(self.descriptors().len(), true)
    }

    fn init_local_state(
        &self,
        _: &Context,
        _: &(),
        _: Option<&()>,
        _: InitColumnData<'_>,
    ) -> Result<Option<Self::LocalState>> {
        Ok(Some((self.active_aliases()?, 0)))
    }

    fn exec(
        &self,
        _: &Context,
        _: &(),
        state: Option<&mut Self::LocalState>,
        _: Option<&()>,
        output: &mut DataChunk<'_>,
        _: ExecColumnInfo<'_>,
    ) -> Result<()> {
        let (active_aliases, offset) =
            state.ok_or_else(|| Error::internal("qw_graph_providers: missing scan state"))?;
        let descriptors = self.descriptors().skip(*offset).take(output.capacity()?);
        let len = descriptors.len();
        if len == 0 {
            return Ok(());
        }
        write_column::<String>(output, 0, descriptors.clone().map(|item| Some(item.id)))?;
        write_column::<String>(output, 1, descriptors.map(|item| Some(item.option)))?;
        let aliases = active_aliases[*offset..*offset + len]
            .iter()
            .map(Option::as_deref);
        write_column::<String>(output, 2, aliases)?;
        *offset += len;
        Ok(())
    }
}

#[cfg(test)]
mod tests;
