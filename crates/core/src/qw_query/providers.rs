//! Bind an alias to the configuration and backend that own it in this DuckDB instance.
use std::{
    collections::{BTreeMap, HashMap, HashSet},
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
    RegisteredConfig, admit_local_path, backend_error, is_identifier, parse_config, remote,
};

/// Describes the catalog evidence needed to rewrite a graph read.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProviderRewrite {
    Disabled,
    LabelCatalog,
    ObservedCatalog,
}

/// Resource class whose host authorization applies to the provider.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProviderSource {
    LocalFile,
    RemoteEndpoint,
}

/// Native-supplied identity, option name, and planner capabilities.
#[derive(Clone, Copy)]
pub struct ProviderDescriptor {
    pub id: &'static str,
    pub name: &'static str,
    pub option: &'static str,
    pub source: ProviderSource,
    pub unknown_alias_error: Option<&'static str>,
    pub accepts_declared_catalog: bool,
    pub supports_timeout: bool,
    pub rewrite: ProviderRewrite,
}

impl ProviderDescriptor {
    fn scope_error(self) -> Error {
        Error::invalid_input(format!("QW_CONFIG: Use SET GLOBAL for {}", self.option))
    }
}

/// An enabled provider and its backend for one DuckDB instance.
#[derive(Clone)]
pub struct GraphProvider {
    pub(super) descriptor: ProviderDescriptor,
    pub(super) backend: Arc<dyn ReadBackend>,
}

impl GraphProvider {
    pub fn new(descriptor: ProviderDescriptor, backend: impl ReadBackend + 'static) -> Self {
        Self {
            descriptor,
            backend: Arc::new(backend),
        }
    }

    pub(super) fn config(&self, context: &Context) -> Result<Option<ConfigSnapshot>> {
        let Some((value, scope)) = context.config()?.try_get_value(self.descriptor.option)? else {
            return Ok(None);
        };
        if matches!(scope, SettingScope::Session) {
            return Err(self.descriptor.scope_error());
        }
        String::from_value(&value)?
            .map(|json| {
                serde_json::from_str(&json)
                    .map_err(|_| Error::invalid_input("QW_CONFIG: Invalid graph configuration"))
            })
            .transpose()
    }
}

fn alias_collision() -> Error {
    Error::invalid_input("QW_CONFIG: Graph alias must be unique across providers")
}

/// The same registry backs configuration, lookup, session selection, and inventory.
#[derive(Clone)]
pub struct ProviderRegistry {
    providers: Arc<[GraphProvider]>,
    reservations: Arc<Mutex<HashMap<&'static str, String>>>,
}

impl ProviderRegistry {
    pub(super) fn new(providers: Vec<GraphProvider>) -> Result<Self> {
        let mut ids = HashSet::new();
        let mut options = HashSet::new();
        for provider in &providers {
            let descriptor = provider.descriptor;
            if !is_identifier(descriptor.id)
                || !ids.insert(descriptor.id.to_ascii_lowercase())
                || !is_identifier(descriptor.option)
                || !options.insert(descriptor.option.to_ascii_lowercase())
            {
                return Err(Error::invalid_input(
                    "QW_CONFIG: Graph provider IDs and settings must be unique identifiers",
                ));
            }
        }
        Ok(Self {
            providers: providers.into(),
            reservations: Arc::default(),
        })
    }

    pub(super) fn register_options(&self, extension: &Extension) -> Result<()> {
        for provider in self.providers.iter() {
            let descriptor = provider.descriptor;
            CustomOptionBuilder::new(
                descriptor.option,
                &format!(
                    "JSON configuration for a read-only {} graph",
                    descriptor.name
                ),
                String::logical_type(extension)?,
                GraphConfig {
                    provider: provider.clone(),
                    registry: self.clone(),
                },
            )
            .default_value(Option::<String>::None.value(extension)?)
            .default_scope(SettingScope::Global)
            .register(extension)?;
        }
        Ok(())
    }

    pub(super) fn descriptors(
        &self,
    ) -> impl ExactSizeIterator<Item = ProviderDescriptor> + Clone + '_ {
        self.providers.iter().map(|provider| provider.descriptor)
    }

    /// Validate a session graph selection against this instance's provisioned names.
    pub fn validate_graph_alias(&self, context: &Context, alias: &str) -> Result<()> {
        self.resolve_alias(context, alias).map(|_| ())
    }

    pub(super) fn resolve_alias(
        &self,
        context: &Context,
        alias: &str,
    ) -> Result<(&GraphProvider, ConfigSnapshot)> {
        let mut matched = None;
        let mut configured = 0;
        let mut unknown_alias_error = None;
        for provider in self.providers.iter() {
            let Some(snapshot) = provider.config(context)? else {
                continue;
            };
            configured += 1;
            unknown_alias_error = provider.descriptor.unknown_alias_error;
            if snapshot.config.alias().eq_ignore_ascii_case(alias)
                && matched.replace((provider, snapshot)).is_some()
            {
                return Err(alias_collision());
            }
        }
        matched.ok_or_else(|| {
            let message = match configured {
                0 => "QW_CONFIG: Configure an existing graph before selecting its alias",
                1 => unknown_alias_error.unwrap_or("QW_CONFIG: Unknown graph alias"),
                _ => "QW_CONFIG: Unknown graph alias",
            };
            Error::invalid_input(message)
        })
    }

    pub(super) fn check_alias_available(
        &self,
        context: &Context,
        provider_id: &str,
        alias: &str,
    ) -> Result<()> {
        for other in self
            .providers
            .iter()
            .filter(|item| item.descriptor.id != provider_id)
        {
            if other
                .config(context)?
                .is_some_and(|snapshot| snapshot.config.alias().eq_ignore_ascii_case(alias))
            {
                return Err(alias_collision());
            }
        }
        Ok(())
    }

    fn reserve_alias(
        &self,
        context: &Context,
        provider_id: &'static str,
        alias: Option<&str>,
    ) -> Result<()> {
        if self.providers.len() < 2 {
            return Ok(());
        }
        let mut reservations = self
            .reservations
            .lock()
            .map_err(|_| Error::internal("QW_CONFIG: Graph alias reservations unavailable"))?;
        // Option callbacks return before DuckDB publishes the value. Keep the
        // reservation until replacement or reset, and check published values at bind and scan start.
        if let Some(alias) = alias {
            if reservations
                .iter()
                .any(|(id, other)| *id != provider_id && other.eq_ignore_ascii_case(alias))
            {
                return Err(alias_collision());
            }
            self.check_alias_available(context, provider_id, alias)?;
            reservations.insert(provider_id, alias.to_owned());
        } else {
            reservations.remove(provider_id);
        }
        Ok(())
    }
}

struct GraphConfig {
    provider: GraphProvider,
    registry: ProviderRegistry,
}

impl CustomOptionCallbacks for GraphConfig {
    fn update(
        &self,
        context: &Context,
        value: Value,
        scope: SettingScope,
        is_reset: bool,
    ) -> Result<Value> {
        let descriptor = self.provider.descriptor;
        if matches!(scope, SettingScope::Session) {
            return Err(descriptor.scope_error());
        }
        let backend = &self.provider.backend;
        if is_reset {
            let value = Option::<String>::None.value(context)?;
            self.registry.reserve_alias(context, descriptor.id, None)?;
            backend.set_generation(None);
            return Ok(value);
        }
        let value = String::from_value(&value)?;
        if descriptor.source == ProviderSource::RemoteEndpoint {
            let text = value.ok_or_else(|| {
                Error::invalid_input("QW_CONFIG: Expected remote graph configuration")
            })?;
            let config = remote::RemoteConfig::parse(&text)?;
            remote::admit_remote(context)?;
            backend
                .validate_remote(&config.source())
                .map_err(backend_error)?;
            let snapshot = ConfigSnapshot {
                generation: GraphGeneration::remote(next_generation()?),
                config: RegisteredConfig::Remote(config),
                catalog: None,
                observed_catalog: false,
                single_pattern_row_bound: None,
                populations: None,
            };
            return self.publish(context, &snapshot);
        }
        let text = value
            .ok_or_else(|| Error::invalid_input("QW_CONFIG: Expected JSON with alias and path"))?;
        let mut config = parse_config(&text)?;
        if !descriptor.accepts_declared_catalog && config.catalog.is_some() {
            return Err(Error::invalid_input(format!(
                "QW_CONFIG: {} discovers its own property catalog",
                descriptor.name
            )));
        }
        if !descriptor.supports_timeout && config.timeout_ms.is_some() {
            return Err(Error::invalid_input(format!(
                "QW_CONFIG: {} does not support timeout_ms",
                descriptor.name
            )));
        }
        let declared = config.catalog.take().map(normalize_catalog).transpose()?;
        config.path = admit_local_path(context, &config.path)?;
        let path = Path::new(&config.path);
        let generation = next_generation()?;
        let registered = GraphGeneration::capture(generation, path)?;
        let prepared = backend
            .prepare_registration(path, declared.as_ref(), generation)
            .map_err(backend_error)?;
        registered.validate(path)?;
        let observed_catalog = declared.is_none()
            && prepared
                .catalog
                .as_ref()
                .is_some_and(|catalog| !catalog.is_empty());
        let snapshot = ConfigSnapshot {
            generation: registered,
            config: RegisteredConfig::Local(config),
            catalog: declared.or(prepared.catalog),
            observed_catalog,
            single_pattern_row_bound: prepared.single_pattern_row_bound,
            populations: prepared.populations,
        };
        let value = self.publish(context, &snapshot)?;
        (prepared.activate)();
        Ok(value)
    }
}

impl GraphConfig {
    fn publish(&self, context: &Context, snapshot: &ConfigSnapshot) -> Result<Value> {
        let json = serde_json::to_string(snapshot).map_err(|_| {
            Error::internal("QW_CONFIG: Could not store the validated graph configuration")
        })?;
        let value = json.value(context)?;
        self.registry.reserve_alias(
            context,
            self.provider.descriptor.id,
            Some(snapshot.config.alias()),
        )?;
        Ok(value)
    }
}

fn next_generation() -> Result<u64> {
    CONFIG_GENERATION
        .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |v| v.checked_add(1))
        .map_err(|_| Error::internal("QW_CONFIG: Configuration generation exhausted"))
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
