//! Host policy and connection metadata for network-backed graph reads.
use duckdb_neo::{
    DuckDBType, FromValue, Result, ToValue,
    connection::{Context, SettingScope},
    custom_option::{CustomOptionBuilder, CustomOptionCallbacks},
    error::Error,
    extension::Extension,
    value::Value,
};
use serde::{Deserialize, Deserializer, Serialize};

use super::DeclaredCatalog;

const ENABLE_REMOTE: &str = "qw_enable_remote_graphs";

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RemoteCredential {
    #[serde(rename = "credential_ref")]
    Environment(String),
    Secret(String),
}

#[derive(Debug, Deserialize, Serialize)]
pub struct RemoteSource {
    pub endpoint: String,
    pub database: String,
    pub credential: RemoteCredential,
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

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RemoteConfigInput {
    alias: String,
    endpoint: String,
    database: String,
    #[serde(default, deserialize_with = "present_reference")]
    credential_ref: Option<String>,
    #[serde(default, deserialize_with = "present_reference")]
    secret: Option<String>,
    timeout_ms: u64,
    max_response_bytes: usize,
    max_batch_bytes: Option<usize>,
    catalog: Option<DeclaredCatalog>,
}

// A missing key is optional, but explicit JSON null is an invalid reference.
fn present_reference<'de, D>(deserializer: D) -> std::result::Result<Option<String>, D::Error>
where
    D: Deserializer<'de>,
{
    String::deserialize(deserializer).map(Some)
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(try_from = "RemoteConfigInput")]
pub(super) struct RemoteConfig {
    pub(super) alias: String,
    endpoint: String,
    database: String,
    #[serde(flatten)]
    credential: RemoteCredential,
    timeout_ms: u64,
    max_response_bytes: usize,
    pub(super) max_batch_bytes: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) catalog: Option<DeclaredCatalog>,
}

impl TryFrom<RemoteConfigInput> for RemoteConfig {
    type Error = &'static str;

    fn try_from(input: RemoteConfigInput) -> std::result::Result<Self, Self::Error> {
        let credential = match (input.credential_ref, input.secret) {
            (Some(reference), None) => RemoteCredential::Environment(reference),
            (None, Some(name)) if !name.is_empty() && !name.contains('\0') => {
                RemoteCredential::Secret(name)
            }
            _ => {
                return Err(
                    "QW_CONFIG: Specify exactly one of credential_ref or a nonempty secret name",
                );
            }
        };

        if !super::is_identifier(&input.alias)
            || input.timeout_ms == 0
            || input.max_response_bytes == 0
            || input.max_batch_bytes == Some(0)
        {
            return Err("QW_CONFIG: Expected a valid alias and positive remote read limits");
        }

        Ok(Self {
            alias: input.alias,
            endpoint: input.endpoint,
            database: input.database,
            credential,
            timeout_ms: input.timeout_ms,
            max_response_bytes: input.max_response_bytes,
            max_batch_bytes: input.max_batch_bytes,
            catalog: input.catalog,
        })
    }
}

impl RemoteConfig {
    pub(super) fn parse(text: &str) -> Result<Self> {
        let input = serde_json::from_str::<RemoteConfigInput>(text).map_err(|_| {
            Error::invalid_input(
                "QW_CONFIG: Expected alias, endpoint, database, a credential reference, timeout_ms and max_response_bytes",
            )
        })?;
        Self::try_from(input).map_err(Error::invalid_input)
    }

    pub(super) fn source(&self) -> RemoteSource {
        RemoteSource {
            endpoint: self.endpoint.clone(),
            database: self.database.clone(),
            credential: self.credential.clone(),
        }
    }

    pub(super) fn limits(&self) -> ScanLimits {
        ScanLimits {
            timeout_ms: self.timeout_ms,
            max_response_bytes: self.max_response_bytes,
        }
    }
}
