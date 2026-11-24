//! Bind an alias to the configuration and backend that own it in this DuckDB instance.
use std::{
    collections::{BTreeMap, HashMap},
    path::Path,
    sync::{Arc, Mutex, atomic::Ordering},
};

use duckdb_neo::{
    DuckDBType, FromValue, Result, ToValue,
    connection::{Context, SettingScope},
    custom_option::{CustomOptionBuilder, CustomOptionCallbacks},
    error::Error,
    extension::Extension,
    value::Value,
};

use super::{
    CONFIG_GENERATION, ConfigSnapshot, GraphCatalog, GraphGeneration, ReadBackend,
    admit_local_path, backend_error, is_identifier, parse_config,
};

#[derive(Clone, Copy, Eq, Hash, PartialEq)]
pub(super) enum ProviderKind {
    Ladybug,
    Relate,
}

impl ProviderKind {
    pub(super) fn name(self) -> &'static str {
        match self {
            Self::Ladybug => "Ladybug",
            Self::Relate => "RelateDB",
        }
    }

    fn option(self) -> &'static str {
        match self {
            Self::Ladybug => "qw_ladybug_config",
            Self::Relate => "qw_relate_config",
        }
    }

    fn other(self) -> Self {
        match self {
            Self::Ladybug => Self::Relate,
            Self::Relate => Self::Ladybug,
        }
    }

    pub(super) fn check_sibling(self, context: &Context, alias: &str) -> Result<()> {
        if self
            .other()
            .config(context)?
            .is_some_and(|other| other.config.alias.eq_ignore_ascii_case(alias))
        {
            return Err(alias_collision());
        }
        Ok(())
    }

    pub(super) fn config(self, context: &Context) -> Result<Option<ConfigSnapshot>> {
        let Some((value, scope)) = context.config()?.try_get_value(self.option())? else {
            // The RelateDB option exists only in builds that include its backend.
            return Ok(None);
        };
        if matches!(scope, SettingScope::Session) {
            return Err(self.scope_error());
        }
        String::from_value(&value)?
            .map(|json| {
                serde_json::from_str(&json)
                    .map_err(|_| Error::invalid_input("QW_CONFIG: Invalid graph configuration"))
            })
            .transpose()
    }

    fn scope_error(self) -> Error {
        Error::invalid_input(format!("QW_CONFIG: Use SET GLOBAL for {}", self.option()))
    }
}

fn alias_collision() -> Error {
    Error::invalid_input("QW_CONFIG: Graph alias must be unique across providers")
}

pub(super) fn resolve_alias(
    context: &Context,
    alias: &str,
    providers: impl IntoIterator<Item = ProviderKind>,
) -> Result<(usize, ConfigSnapshot)> {
    let mut matched = None;
    let mut has_ladybug = false;
    let mut has_relate = false;
    for (index, kind) in providers.into_iter().enumerate() {
        let Some(snapshot) = kind.config(context)? else {
            continue;
        };
        match kind {
            ProviderKind::Ladybug => has_ladybug = true,
            ProviderKind::Relate => has_relate = true,
        }
        if snapshot.config.alias.eq_ignore_ascii_case(alias)
            && matched.replace((index, snapshot)).is_some()
        {
            return Err(alias_collision());
        }
    }
    matched.ok_or_else(|| {
        Error::invalid_input(match (has_ladybug, has_relate) {
            (false, false) => "QW_CONFIG: Configure an existing graph before selecting its alias",
            (true, false) => "QW_CONFIG: Unknown Ladybug graph alias",
            _ => "QW_CONFIG: Unknown graph alias",
        })
    })
}

#[derive(Clone)]
pub(super) struct GraphProvider {
    pub(super) kind: ProviderKind,
    pub(super) backend: Arc<dyn ReadBackend>,
}

/// DuckDB publishes the value after its option callback returns. Reserve the alias
/// across callbacks on this instance, including the interval before publication.
#[derive(Default)]
pub(super) struct AliasReservations(Mutex<HashMap<ProviderKind, String>>);

impl AliasReservations {
    fn update(
        &self,
        context: &Context,
        kind: ProviderKind,
        next: Option<&ConfigSnapshot>,
    ) -> Result<()> {
        let mut reservations = self
            .0
            .lock()
            .map_err(|_| Error::internal("QW_CONFIG: Graph alias reservations unavailable"))?;
        // SET and RESET may finish in a different order after their callbacks.
        // Always let a provider replace or clear its own reservation. DuckDB's
        // published snapshots are authoritative at bind and again at scan start.
        if let Some(snapshot) = next {
            let alias = &snapshot.config.alias;
            if reservations
                .get(&kind.other())
                .is_some_and(|other| alias.eq_ignore_ascii_case(other))
            {
                return Err(alias_collision());
            }
            kind.check_sibling(context, alias)?;
            reservations.insert(kind, alias.to_owned());
        } else {
            reservations.remove(&kind);
        }
        Ok(())
    }
}

impl GraphProvider {
    pub(super) fn new(kind: ProviderKind, backend: impl ReadBackend + 'static) -> Self {
        Self {
            kind,
            backend: Arc::new(backend),
        }
    }

    pub(super) fn register_option(
        &self,
        extension: &Extension,
        aliases: Option<Arc<AliasReservations>>,
    ) -> Result<()> {
        CustomOptionBuilder::new(
            self.kind.option(),
            &format!(
                "JSON configuration for an embedded read-only {} graph",
                self.kind.name()
            ),
            String::logical_type(extension)?,
            GraphConfig {
                provider: self.clone(),
                aliases,
            },
        )
        .default_value(Option::<String>::None.value(extension)?)
        .default_scope(SettingScope::Global)
        .register(extension)?;
        Ok(())
    }
}

struct GraphConfig {
    provider: GraphProvider,
    aliases: Option<Arc<AliasReservations>>,
}

impl CustomOptionCallbacks for GraphConfig {
    fn update(
        &self,
        context: &Context,
        value: Value,
        scope: SettingScope,
        is_reset: bool,
    ) -> Result<Value> {
        let kind = self.provider.kind;
        if matches!(scope, SettingScope::Session) {
            return Err(kind.scope_error());
        }
        let backend = &self.provider.backend;
        if is_reset {
            let value = Option::<String>::None.value(context)?;
            if let Some(aliases) = &self.aliases {
                aliases.update(context, kind, None)?;
            }
            backend.set_generation(None);
            return Ok(value);
        }
        let text = String::from_value(&value)?
            .ok_or_else(|| Error::invalid_input("QW_CONFIG: Expected JSON with alias and path"))?;
        let mut config = parse_config(&text)?;
        if kind == ProviderKind::Ladybug && config.catalog.is_some() {
            return Err(Error::invalid_input(
                "QW_CONFIG: Ladybug discovers its own property catalog",
            ));
        }
        if kind == ProviderKind::Relate && config.timeout_ms.is_some() {
            return Err(Error::invalid_input(
                "QW_CONFIG: RelateDB does not support timeout_ms",
            ));
        }
        let declared = config.catalog.take().map(normalize_catalog).transpose()?;
        config.path = admit_local_path(context, &config.path)?;
        let path = Path::new(&config.path);
        let generation = CONFIG_GENERATION
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |v| v.checked_add(1))
            .map_err(|_| Error::internal("QW_CONFIG: Configuration generation exhausted"))?;
        let registered = GraphGeneration::capture(generation, path)?;
        let prepared = backend
            .prepare_registration(path, declared.as_ref(), generation)
            .map_err(backend_error)?;
        registered.validate(path)?;
        let snapshot = ConfigSnapshot {
            generation: registered,
            config,
            catalog: declared.or(prepared.catalog),
            single_pattern_row_bound: prepared.single_pattern_row_bound,
        };
        let json = serde_json::to_string(&snapshot).map_err(|_| {
            Error::internal("QW_CONFIG: Could not store the validated graph configuration")
        })?;
        let value = json.value(context)?;
        if let Some(aliases) = &self.aliases {
            aliases.update(context, kind, Some(&snapshot))?;
        }
        (prepared.activate)();
        Ok(value)
    }
}

fn normalize_catalog(labels: BTreeMap<String, BTreeMap<String, String>>) -> Result<GraphCatalog> {
    fn check_name(name: &str) -> Result<()> {
        if !is_identifier(name) {
            return Err(Error::invalid_input(
                "QW_CONFIG: Catalog labels and properties require simple identifiers",
            ));
        }
        Ok(())
    }

    labels
        .into_iter()
        .map(|(label, properties)| {
            check_name(&label)?;
            let fields = properties
                .into_iter()
                .map(|(name, ty)| {
                    check_name(&name)?;
                    let native = match ty.to_ascii_uppercase().as_str() {
                        "BOOLEAN" => "BOOL",
                        "BIGINT" => "INT64",
                        "DOUBLE" => "DOUBLE",
                        "VARCHAR" => "STRING",
                        _ => {
                            return Err(Error::invalid_input(
                                "QW_CONFIG: Expected BOOLEAN, BIGINT, DOUBLE or VARCHAR in catalog",
                            ));
                        }
                    };
                    Ok((name, native.to_owned()))
                })
                .collect::<Result<Vec<_>>>()?;
            Ok((label, fields))
        })
        .collect()
}
