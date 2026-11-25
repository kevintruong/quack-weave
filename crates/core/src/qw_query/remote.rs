//! Host policy and connection metadata for network-backed graph reads.
use duckdb_neo::{
    DuckDBType, FromValue, Result, ToValue,
    connection::{Context, SettingScope},
    custom_option::{CustomOptionBuilder, CustomOptionCallbacks},
    error::Error,
    extension::Extension,
    value::Value,
};
use serde::{Deserialize, Serialize};

const ENABLE_REMOTE: &str = "qw_enable_remote_graphs";

#[derive(Debug, Deserialize, Serialize)]
pub struct RemoteSource {
    pub endpoint: String,
    pub database: String,
    pub credential_ref: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct ScanLimits {
    pub timeout_ms: u64,
    pub max_response_bytes: usize,
}

fn has_external_access(context: &Context) -> Result<bool> {
    let (value, _) = context.config()?.get_value("enable_external_access")?;
    Ok(bool::from_value(&value)? == Some(true))
}

fn require_external_access(context: &Context) -> Result<()> {
    if !has_external_access(context)? {
        return Err(Error::invalid_input(
            "QW_ACCESS: Remote graph reads require DuckDB external access",
        ));
    }
    Ok(())
}

pub(super) fn admit_remote(context: &Context) -> Result<()> {
    require_external_access(context)?;
    let (value, scope) = context.config()?.get_value(ENABLE_REMOTE)?;
    if matches!(scope, SettingScope::Session) || bool::from_value(&value)? != Some(true) {
        return Err(Error::invalid_input(
            "QW_ACCESS: Remote graph reads require SET GLOBAL qw_enable_remote_graphs = true",
        ));
    }
    Ok(())
}

struct RemoteAccess;

impl CustomOptionCallbacks for RemoteAccess {
    fn update(
        &self,
        context: &Context,
        value: Value,
        scope: SettingScope,
        is_reset: bool,
    ) -> Result<Value> {
        if matches!(scope, SettingScope::Session) {
            return Err(Error::invalid_input(
                "QW_CONFIG: Use SET GLOBAL for qw_enable_remote_graphs",
            ));
        }
        if is_reset {
            return false.value(context);
        }
        let enabled = bool::from_value(&value)?.ok_or_else(|| {
            Error::invalid_input("QW_CONFIG: Expected a boolean for qw_enable_remote_graphs")
        })?;
        if enabled {
            require_external_access(context)?;
        }
        Ok(value)
    }
}

pub(super) fn register(extension: &Extension) -> Result<()> {
    CustomOptionBuilder::new(
        ENABLE_REMOTE,
        "Allow reads from registered remote graph endpoints",
        bool::logical_type(extension)?,
        RemoteAccess,
    )
    .default_value(false.value(extension)?)
    .default_scope(SettingScope::Global)
    .register(extension)?;
    Ok(())
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct RemoteConfig {
    pub(super) alias: String,
    endpoint: String,
    database: String,
    credential_ref: String,
    timeout_ms: u64,
    max_response_bytes: usize,
    pub(super) max_batch_bytes: Option<usize>,
}

impl RemoteConfig {
    pub(super) fn parse(text: &str) -> Result<Self> {
        let config: Self = serde_json::from_str(text).map_err(|_| {
            Error::invalid_input(
                "QW_CONFIG: Expected alias, endpoint, database, credential_ref, timeout_ms and max_response_bytes",
            )
        })?;
        if !super::is_identifier(&config.alias)
            || config.timeout_ms == 0
            || config.max_response_bytes == 0
            || config.max_batch_bytes == Some(0)
        {
            return Err(Error::invalid_input(
                "QW_CONFIG: Expected a valid alias and positive remote read limits",
            ));
        }
        Ok(config)
    }

    pub(super) fn source(&self) -> RemoteSource {
        RemoteSource {
            endpoint: self.endpoint.clone(),
            database: self.database.clone(),
            credential_ref: self.credential_ref.clone(),
        }
    }

    pub(super) fn limits(&self) -> ScanLimits {
        ScanLimits {
            timeout_ms: self.timeout_ms,
            max_response_bytes: self.max_response_bytes,
        }
    }
}
