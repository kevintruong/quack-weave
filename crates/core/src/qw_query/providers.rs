//! Bind an alias to the configuration and backend that own it in this DuckDB instance.
use std::{
    collections::{HashMap, HashSet},
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
    CONFIG_GENERATION, ConfigSnapshot, DeclaredCatalog, GraphCatalog, GraphGeneration, ReadBackend,
    RegisteredConfig, RetiredRegistration, admit_local_path, backend_error, is_identifier,
    parse_config, remote,
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
}

fn alias_collision() -> Error {
    Error::invalid_input("QW_CONFIG: Graph alias must be unique across providers")
}

#[derive(Default)]
struct ProviderSlot {
    revision: u64,
    active: Option<Arc<ConfigSnapshot>>,
}

struct RegistryState {
    slots: HashMap<&'static str, ProviderSlot>,
    aliases: HashMap<String, &'static str>,
}

impl RegistryState {
    fn slot(&self, provider_id: &str) -> Result<&ProviderSlot> {
        self.slots.get(provider_id).ok_or_else(unknown_provider)
    }

    fn replace(
        &mut self,
        provider_id: &'static str,
        snapshot: Option<Arc<ConfigSnapshot>>,
        alias: Option<String>,
    ) -> Result<Option<Arc<ConfigSnapshot>>> {
        let slot = self
            .slots
            .get_mut(provider_id)
            .ok_or_else(unknown_provider)?;
        slot.revision = slot
            .revision
            .checked_add(1)
            .ok_or_else(|| Error::internal("QW_CONFIG: Graph registration revision exhausted"))?;
        let previous = std::mem::replace(&mut slot.active, snapshot);
        if let Some(previous) = &previous {
            self.aliases
                .remove(&previous.config.alias().to_ascii_lowercase());
        }
        if let Some(alias) = alias {
            self.aliases.insert(alias, provider_id);
        }
        Ok(previous)
    }
}

fn unknown_provider() -> Error {
    Error::internal("QW_CONFIG: Unknown graph provider")
}

/// The same registry backs configuration, lookup, session selection, and inventory.
#[derive(Clone)]
pub struct ProviderRegistry {
    providers: Arc<[GraphProvider]>,
    state: Arc<Mutex<RegistryState>>,
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
        let slots = providers
            .iter()
            .map(|provider| (provider.descriptor.id, ProviderSlot::default()))
            .collect();
        Ok(Self {
            providers: providers.into(),
            state: Arc::new(Mutex::new(RegistryState {
                slots,
                aliases: HashMap::new(),
            })),
        })
    }

    fn state(&self) -> Result<std::sync::MutexGuard<'_, RegistryState>> {
        self.state
            .lock()
            .map_err(|_| Error::internal("QW_CONFIG: Graph registry unavailable"))
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
    pub fn validate_graph_alias(&self, alias: &str) -> Result<()> {
        self.resolve_alias(alias).map(|_| ())
    }

    pub(super) fn resolve_alias(
        &self,
        alias: &str,
    ) -> Result<(&GraphProvider, Arc<ConfigSnapshot>)> {
        let alias = alias.to_ascii_lowercase();
        let state = self.state()?;
        if let Some(id) = state.aliases.get(&alias) {
            let provider = self
                .providers
                .iter()
                .find(|provider| provider.descriptor.id == *id)
                .ok_or_else(unknown_provider)?;
            let snapshot = state
                .slot(id)?
                .active
                .clone()
                .ok_or_else(unknown_provider)?;
            return Ok((provider, snapshot));
        }
        let message = match state.aliases.len() {
            0 => "QW_CONFIG: Configure an existing graph before selecting its alias",
            1 => self
                .providers
                .iter()
                .find(|provider| state.slots[provider.descriptor.id].active.is_some())
                .and_then(|provider| provider.descriptor.unknown_alias_error)
                .unwrap_or("QW_CONFIG: Unknown graph alias"),
            _ => "QW_CONFIG: Unknown graph alias",
        };
        Err(Error::invalid_input(message))
    }

    pub(super) fn active_aliases(&self) -> Result<Vec<Option<String>>> {
        let state = self.state()?;
        Ok(self
            .providers
            .iter()
            .map(|provider| {
                state.slots[provider.descriptor.id]
                    .active
                    .as_ref()
                    .map(|snapshot| snapshot.config.alias().to_owned())
            })
            .collect())
    }

    fn snapshot(&self, provider_id: &str) -> Result<Option<Arc<ConfigSnapshot>>> {
        Ok(self.state()?.slot(provider_id)?.active.clone())
    }

    pub(super) fn check_generation(&self, provider_id: &str, generation: u64) -> Result<bool> {
        Ok(self
            .snapshot(provider_id)?
            .is_some_and(|snapshot| snapshot.generation.id() == generation))
    }

    fn revision(&self, provider_id: &str) -> Result<u64> {
        Ok(self.state()?.slot(provider_id)?.revision)
    }

    fn commit(
        &self,
        provider_id: &'static str,
        expected_revision: u64,
        snapshot: Arc<ConfigSnapshot>,
        activate: impl FnOnce() -> Option<RetiredRegistration>,
    ) -> Result<()> {
        let alias = snapshot.config.alias().to_ascii_lowercase();
        let (previous, retired) = {
            let mut state = self.state()?;
            if state.slot(provider_id)?.revision != expected_revision {
                return Err(Error::invalid_input(
                    "QW_CONFIG: Graph registration changed during preparation",
                ));
            }
            if state
                .aliases
                .get(&alias)
                .is_some_and(|owner| *owner != provider_id)
            {
                return Err(alias_collision());
            }
            let previous = state.replace(provider_id, Some(snapshot), Some(alias))?;
            (previous, activate())
        };
        drop(previous);
        drop(retired);
        Ok(())
    }

    fn reset(
        &self,
        provider_id: &'static str,
        deactivate: impl FnOnce() -> Option<RetiredRegistration>,
    ) -> Result<()> {
        let (previous, retired) = {
            let mut state = self.state()?;
            // Keep the tombstone revision even for an empty slot to cancel in-flight preparation.
            let previous = state.replace(provider_id, None, None)?;
            (previous, deactivate())
        };
        drop(previous);
        drop(retired);
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
            self.registry
                .reset(descriptor.id, || backend.set_generation(None))?;
            return Ok(value);
        }
        let expected_revision = self.registry.revision(descriptor.id)?;
        let value = String::from_value(&value)?;
        if descriptor.source == ProviderSource::RemoteEndpoint {
            let text = value.ok_or_else(|| {
                Error::invalid_input("QW_CONFIG: Expected remote graph configuration")
            })?;
            let mut config = remote::RemoteConfig::parse(&text)?;
            if !descriptor.accepts_declared_catalog && config.catalog.is_some() {
                return Err(Error::invalid_input(
                    "QW_CONFIG: This remote provider does not accept a declared catalog",
                ));
            }
            let catalog = config
                .catalog
                .take()
                .map(|catalog| normalize_catalog(catalog, true))
                .transpose()?;
            remote::admit_remote(context)?;
            backend
                .validate_remote(&config.source())
                .map_err(backend_error)?;
            let snapshot = ConfigSnapshot {
                generation: GraphGeneration::remote(next_generation()?),
                config: RegisteredConfig::Remote(config),
                catalog,
                observed_catalog: false,
                single_pattern_row_bound: None,
                populations: None,
            };
            return self.publish(context, expected_revision, snapshot, || None);
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
        let declared = config
            .catalog
            .take()
            .map(|catalog| normalize_catalog(catalog, false))
            .transpose()?;
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
        self.publish(context, expected_revision, snapshot, prepared.activate)
    }
}

impl GraphConfig {
    fn publish(
        &self,
        context: &Context,
        expected_revision: u64,
        snapshot: ConfigSnapshot,
        activate: impl FnOnce() -> Option<RetiredRegistration>,
    ) -> Result<Value> {
        // DuckDB copies this value into its setting after the callback returns. It
        // mirrors sequential writes, but scan authority lives in the registry.
        let json = serde_json::to_string(&snapshot).map_err(|_| {
            Error::internal("QW_CONFIG: Could not store the validated graph configuration")
        })?;
        let value = json.value(context)?;
        self.registry.commit(
            self.provider.descriptor.id,
            expected_revision,
            Arc::new(snapshot),
            activate,
        )?;
        Ok(value)
    }
}

fn next_generation() -> Result<u64> {
    CONFIG_GENERATION
        .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |v| v.checked_add(1))
        .map_err(|_| Error::internal("QW_CONFIG: Configuration generation exhausted"))
}

fn normalize_catalog(labels: DeclaredCatalog, kind_qualified: bool) -> Result<GraphCatalog> {
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
            let name = if kind_qualified {
                match label.split_once(':') {
                    Some(("node" | "relationship", name)) => name,
                    _ => {
                        return Err(Error::invalid_input(
                            "QW_CONFIG: Remote catalog entries require node: or relationship: prefixes",
                        ));
                    }
                }
            } else {
                &label
            };
            check_name(name)?;
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        sync::{Barrier, atomic::AtomicBool},
        thread,
    };

    struct FixtureBackend;
    impl ReadBackend for FixtureBackend {}

    fn fixture_provider(id: &'static str, option: &'static str) -> GraphProvider {
        GraphProvider::new(
            ProviderDescriptor {
                id,
                name: id,
                option,
                source: ProviderSource::RemoteEndpoint,
                unknown_alias_error: None,
                accepts_declared_catalog: false,
                supports_timeout: true,
                rewrite: ProviderRewrite::Disabled,
            },
            FixtureBackend,
        )
    }

    fn fixture_snapshot(generation: u64, alias: &str) -> Arc<ConfigSnapshot> {
        let config = remote::RemoteConfig::parse(
            &serde_json::json!({
                "alias": alias,
                "endpoint": "https://fixture.invalid",
                "database": "test",
                "credential_ref": "test",
                "timeout_ms": 1,
                "max_response_bytes": 1,
            })
            .to_string(),
        )
        .unwrap();
        Arc::new(ConfigSnapshot {
            generation: GraphGeneration::remote(generation),
            config: RegisteredConfig::Remote(config),
            catalog: None,
            observed_catalog: false,
            single_pattern_row_bound: None,
            populations: None,
        })
    }

    #[test]
    fn reset_invalidates_pending_registration_before_peer_claims_alias() {
        let registry = ProviderRegistry::new(vec![
            fixture_provider("first", "first_config"),
            fixture_provider("second", "second_config"),
        ])
        .unwrap();
        let prepared = Barrier::new(2);
        let peer_registered = Barrier::new(2);
        let stale_activated = AtomicBool::new(false);
        let revision = registry.revision("first").unwrap();
        let snapshot = fixture_snapshot(1, "Shared");
        thread::scope(|scope| {
            let pending = scope.spawn(|| {
                prepared.wait();
                peer_registered.wait();
                registry.commit("first", revision, snapshot, || {
                    stale_activated.store(true, Ordering::Relaxed);
                    None
                })
            });
            prepared.wait();
            let reset = registry.reset("first", || None);
            let competing = registry.revision("second").and_then(|revision| {
                registry.commit("second", revision, fixture_snapshot(2, "sHARED"), || None)
            });
            peer_registered.wait();
            reset.unwrap();
            competing.unwrap();
            let error = pending.join().unwrap().unwrap_err();
            assert!(
                error
                    .to_string()
                    .contains("registration changed during preparation")
            );
        });
        assert!(!stale_activated.load(Ordering::Relaxed));
        assert!(registry.snapshot("first").unwrap().is_none());
        assert_eq!(
            registry.snapshot("second").unwrap().unwrap().config.alias(),
            "sHARED"
        );
        assert!(registry.check_generation("second", 2).unwrap());
        registry.reset("second", || None).unwrap();
        assert!(!registry.check_generation("second", 2).unwrap());
    }
}
