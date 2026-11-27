//! Each attachment belongs to a private Ladybug database and connection.
use std::ffi::{CStr, CString, c_char, c_void};
use std::path::Path;
use std::sync::{Arc, Mutex};

use duckdb_neo::{AsRaw, connection::Context};
use rusty_quack_core::qw_query::{
    BackendError, BatchReader, CloudSource, CloudStorage, ColumnSpec, GraphCatalog, GraphParameter,
    ReadSession,
};

use super::{Connection, Database, QueryResult, Session, admit_graph_read, execution_error, ffi};

#[repr(C)]
struct SecretText {
    data: *const u8,
    len: usize,
}

impl SecretText {
    // The DuckDB visitor keeps the backing string alive until the callback returns.
    unsafe fn copy(&self) -> Option<String> {
        let bytes = unsafe { std::slice::from_raw_parts(self.data, self.len) };
        Some(std::str::from_utf8(bytes).ok()?.to_owned())
    }
}

#[repr(C)]
struct SecretFields {
    key_id: SecretText,
    secret: SecretText,
    token: SecretText,
    region: SecretText,
}

unsafe extern "C" {
    fn qw_ladybug_attached_catalog(
        connection: *mut ffi::ConnectionHandle,
        alias: *const c_char,
        output: *mut c_void,
        visit: unsafe extern "C" fn(
            *mut c_void,
            *const c_char,
            *const c_char,
            *const c_char,
        ) -> bool,
    ) -> bool;
    fn qw_visit_ladybug_cloud_secret(
        context: *mut c_void,
        name: *const u8,
        name_size: usize,
        path: *const u8,
        path_size: usize,
        gcs: bool,
        state: *mut c_void,
        visit: unsafe extern "C" fn(*mut c_void, SecretFields),
    ) -> bool;
}

struct Credential {
    key_id: String,
    secret: String,
    token: String,
    region: String,
}

unsafe extern "C" fn copy_credential(state: *mut c_void, fields: SecretFields) {
    let copy = || unsafe {
        Some(Credential {
            key_id: fields.key_id.copy()?,
            secret: fields.secret.copy()?,
            token: fields.token.copy()?,
            region: fields.region.copy()?,
        })
    };
    let output = unsafe { &mut *state.cast::<Option<Credential>>() };
    *output = copy();
}

impl Credential {
    fn resolve(context: &Context, source: &CloudSource) -> Result<Self, BackendError> {
        let mut result = None::<Self>;
        let found = unsafe {
            qw_visit_ladybug_cloud_secret(
                context.get_raw().cast(),
                source.secret.as_ptr(),
                source.secret.len(),
                source.uri.as_ptr(),
                source.uri.len(),
                source.storage == CloudStorage::Gcs,
                (&raw mut result).cast(),
                copy_credential,
            )
        };
        if !found {
            return Err(BackendError::RemoteAuth);
        }
        result.ok_or(BackendError::RemoteAuth)
    }
}

struct Endpoint {
    host: String,
    disable_ssl: bool,
}

impl Endpoint {
    fn new(storage: CloudStorage, region: &str) -> Result<Self, BackendError> {
        if storage == CloudStorage::S3 && !valid_region(region) {
            return Err(BackendError::RemoteConfig);
        }
        #[cfg(feature = "ladybug-cloud-test-fixture")]
        if let Ok(host) = std::env::var("QW_LADYBUG_CLOUD_FIXTURE_ENDPOINT") {
            if host
                .strip_prefix("127.0.0.1:")
                .filter(|port| port.bytes().all(|b| b.is_ascii_digit()))
                .and_then(|port| port.parse::<u16>().ok())
                .is_some_and(|port| port != 0)
            {
                return Ok(Self {
                    host,
                    disable_ssl: true,
                });
            }
            return Err(BackendError::RemoteConfig);
        }
        let host = match storage {
            CloudStorage::S3 => format!("s3.{region}.amazonaws.com"),
            CloudStorage::Gcs => "storage.googleapis.com".to_owned(),
        };
        Ok(Self {
            host,
            disable_ssl: false,
        })
    }
}

fn valid_region(region: &str) -> bool {
    let Some((area, number)) = region.rsplit_once('-') else {
        return false;
    };
    area.split_once('-').is_some_and(|(country, area)| {
        country.len() == 2
            && country.bytes().all(|b| b.is_ascii_lowercase())
            && area
                .split('-')
                .all(|part| !part.is_empty() && part.bytes().all(|b| b.is_ascii_lowercase()))
    }) && !number.is_empty()
        && number.bytes().all(|b| b.is_ascii_digit())
}

pub(super) struct Pending {
    storage: CloudStorage,
    endpoint: Endpoint,
    credential: Credential,
    uri: String,
    timeout_ms: Option<u64>,
    nested: bool,
}

impl Pending {
    pub(super) fn new(
        context: &Context,
        source: &CloudSource,
        timeout_ms: Option<u64>,
        schema: &[ColumnSpec],
    ) -> Result<Self, BackendError> {
        let credential = Credential::resolve(context, source)?;
        Ok(Self {
            storage: source.storage,
            endpoint: Endpoint::new(source.storage, &credential.region)?,
            credential,
            uri: source.uri.clone(),
            timeout_ms,
            nested: schema.iter().any(|column| column.data_type.is_nested()),
        })
    }

    fn attach(self) -> Result<Session, BackendError> {
        let database = Arc::new(Mutex::new(Database::open(Path::new(":memory:"), false)?));
        let mut session = Session::connect_native(database, self.timeout_ms, self.nested)?;
        let connection = &mut session.connection;
        // The matching HTTPFS is auto-loaded from the static Ladybug build.
        let prefix = match self.storage {
            CloudStorage::S3 => "s3",
            CloudStorage::Gcs => "gcs",
        };
        for (setting, value) in [
            ("access_key_id", self.credential.key_id.as_str()),
            ("secret_access_key", self.credential.secret.as_str()),
            ("session_token", self.credential.token.as_str()),
            ("url_style", "path"),
            ("endpoint", self.endpoint.host.as_str()),
        ] {
            set_string(connection, prefix, setting, value)?;
        }
        if self.storage == CloudStorage::S3 {
            set_string(connection, prefix, "region", &self.credential.region)?;
        }
        let ssl = CString::new(format!("{prefix}_disable_ssl")).map_err(|_| BackendError::Open)?;
        set_bool(connection, &ssl, self.endpoint.disable_ssl)?;
        set_bool(connection, c"http_cache_file", false)?;

        // Escape both Cypher string delimiters. The core source parser also validates the URI.
        let escaped = self.uri.replace('\\', "\\\\").replace('\'', "\\'");
        let attach = CString::new(format!("ATTACH '{escaped}' AS qw_snapshot (dbtype lbug)"))
            .map_err(|_| BackendError::RemoteConfig)?;
        command(
            connection,
            &attach,
            self.timeout_ms,
            BackendError::RemoteTransport,
        )?;
        Ok(session)
    }
}

impl ReadSession for Pending {
    fn execute_with_params(
        self: Box<Self>,
        cypher: &str,
        params: &[(String, GraphParameter)],
    ) -> Result<Box<dyn BatchReader>, BackendError> {
        let cypher = admit_graph_read(cypher)?;
        Box::new(self.attach()?).execute_admitted(&cypher, params)
    }
}

pub(super) fn catalog(
    context: &Context,
    source: &CloudSource,
    timeout_ms: Option<u64>,
) -> Result<GraphCatalog, BackendError> {
    let mut session = Pending::new(context, source, timeout_ms, &[])?.attach()?;
    command(
        &mut session.connection,
        c"BEGIN TRANSACTION READ ONLY",
        timeout_ms,
        BackendError::Schema,
    )?;
    let mut catalog = GraphCatalog::new();
    let ok = unsafe {
        qw_ladybug_attached_catalog(
            &mut session.connection.0,
            c"qw_snapshot".as_ptr(),
            (&raw mut catalog).cast(),
            collect_property,
        )
    };
    ok.then_some(catalog).ok_or(BackendError::Schema)
}

unsafe extern "C" fn collect_property(
    output: *mut c_void,
    label: *const c_char,
    name: *const c_char,
    ty: *const c_char,
) -> bool {
    let catalog = unsafe { &mut *output.cast::<GraphCatalog>() };
    let Ok(label) = (unsafe { CStr::from_ptr(label) }).to_str() else {
        return false;
    };
    let properties = catalog.entry(label.to_owned()).or_default();
    if !name.is_null() {
        let (Ok(name), Ok(ty)) = (
            unsafe { CStr::from_ptr(name) }.to_str(),
            unsafe { CStr::from_ptr(ty) }.to_str(),
        ) else {
            return false;
        };
        properties.push((name.to_owned(), ty.to_owned()));
    }
    true
}

fn set_string(
    connection: &mut Connection,
    prefix: &str,
    setting: &str,
    value: &str,
) -> Result<(), BackendError> {
    let key = CString::new(format!("{prefix}_{setting}")).map_err(|_| BackendError::Open)?;
    // Pass secret values directly to Ladybug's client configuration, outside query text.
    let ok = unsafe {
        ffi::qw_ladybug_set_extension_string(
            &mut connection.0,
            key.as_ptr(),
            value.as_ptr(),
            value.len(),
        )
    };
    ok.then_some(()).ok_or(BackendError::Open)
}

fn set_bool(connection: &mut Connection, key: &CStr, value: bool) -> Result<(), BackendError> {
    let ok = unsafe { ffi::qw_ladybug_set_extension_bool(&mut connection.0, key.as_ptr(), value) };
    ok.then_some(()).ok_or(BackendError::Open)
}

fn command(
    connection: &mut Connection,
    statement: &CStr,
    timeout_ms: Option<u64>,
    failure: BackendError,
) -> Result<(), BackendError> {
    let mut result = QueryResult::default();
    let state =
        unsafe { ffi::lbug_connection_query(&mut connection.0, statement.as_ptr(), &mut result.0) };
    if state == ffi::SUCCESS {
        return Ok(());
    }
    match execution_error(timeout_ms.is_some()) {
        BackendError::Timeout => Err(BackendError::Timeout),
        _ => Err(failure),
    }
}

#[cfg(test)]
mod tests {
    use super::valid_region;

    #[test]
    fn region_is_one_dns_label_with_an_aws_region_shape() {
        assert!(valid_region("ap-southeast-1"));
        assert!(valid_region("us-gov-west-1"));
        for invalid in [
            "",
            "us--east-1",
            "us.east-1",
            "US-east-1",
            "us-east-1/extra",
        ] {
            assert!(!valid_region(invalid));
        }
    }
}
