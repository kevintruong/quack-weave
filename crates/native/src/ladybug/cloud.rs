//! Read-only attachments scoped to a DuckDB connection and a registered graph generation.
mod scope;

use std::collections::HashMap;
use std::ffi::{CStr, CString, c_char, c_void};
use std::path::Path;
use std::sync::{Arc, Mutex, TryLockError};

use scope::Scope;

use duckdb_neo::{AsRaw, connection::Context};
use rusty_quack_core::qw_query::{
    BackendError, BatchReader, CloudSource, CloudStorage, ColumnSpec, GraphCatalog, GraphParameter,
    ReadSession,
};

use super::{
    Connection, Database, DatabaseCache, QueryResult, Session, admit_graph_read, execution_error,
    ffi,
};

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

#[derive(PartialEq, Eq)]
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
        let secret = source.secret.as_deref().ok_or(BackendError::RemoteConfig)?;
        let mut result = None::<Self>;
        let found = unsafe {
            qw_visit_ladybug_cloud_secret(
                context.get_raw().cast(),
                secret.as_ptr(),
                secret.len(),
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

#[derive(PartialEq, Eq)]
struct Endpoint {
    prefix: &'static str,
    host: String,
    disable_ssl: bool,
}

impl Endpoint {
    fn new(storage: CloudStorage, region: &str) -> Result<Self, BackendError> {
        let (prefix, host) = match storage {
            CloudStorage::S3 if valid_region(region) => {
                ("s3", format!("s3.{region}.amazonaws.com"))
            }
            CloudStorage::Gcs => ("gcs", "storage.googleapis.com".to_owned()),
            _ => return Err(BackendError::RemoteConfig),
        };
        #[cfg(feature = "ladybug-cloud-test-fixture")]
        if let Ok(host) = std::env::var("QW_LADYBUG_CLOUD_FIXTURE_ENDPOINT") {
            if host
                .strip_prefix("127.0.0.1:")
                .filter(|port| port.bytes().all(|b| b.is_ascii_digit()))
                .and_then(|port| port.parse::<u16>().ok())
                .is_some_and(|port| port != 0)
            {
                return Ok(Self {
                    prefix,
                    host,
                    disable_ssl: true,
                });
            }
            return Err(BackendError::RemoteConfig);
        }
        Ok(Self {
            prefix,
            host,
            disable_ssl: false,
        })
    }
}

#[derive(PartialEq, Eq)]
struct ObjectStoreAuth {
    credential: Credential,
    endpoint: Endpoint,
}

impl ObjectStoreAuth {
    fn resolve(context: &Context, source: &CloudSource) -> Result<Option<Self>, BackendError> {
        if source.storage == CloudStorage::Xet {
            return source
                .secret
                .is_none()
                .then_some(None)
                .ok_or(BackendError::RemoteConfig);
        }
        let credential = Credential::resolve(context, source)?;
        let endpoint = Endpoint::new(source.storage, &credential.region)?;
        Ok(Some(Self {
            credential,
            endpoint,
        }))
    }

    fn configure(&self, connection: &mut Connection) -> Result<(), BackendError> {
        let prefix = self.endpoint.prefix;
        for (setting, value) in [
            ("access_key_id", self.credential.key_id.as_str()),
            ("secret_access_key", self.credential.secret.as_str()),
            ("session_token", self.credential.token.as_str()),
            ("url_style", "path"),
            ("endpoint", self.endpoint.host.as_str()),
        ] {
            set_string(connection, prefix, setting, value)?;
        }
        if prefix == "s3" {
            set_string(connection, prefix, "region", &self.credential.region)?;
        }
        let ssl = CString::new(format!("{prefix}_disable_ssl")).map_err(|_| BackendError::Open)?;
        set_bool(connection, &ssl, self.endpoint.disable_ssl)
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

// Each generation owns one slot per DuckDB ClientContext. Changed authentication
// replaces the slot, so an admitted scan cannot repopulate its successor.
#[derive(Default)]
pub(super) struct Cache(Mutex<HashMap<u64, Arc<Slot>>>);

impl Cache {
    fn select(&self, id: u64, uri: &str, auth: Option<ObjectStoreAuth>) -> Arc<Slot> {
        let mut slots = self.0.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(slot) = slots.get(&id)
            && slot.uri == uri
            && slot.auth == auth
        {
            return Arc::clone(slot);
        }
        let slot = Slot::new(uri, auth);
        let retired = slots.insert(id, Arc::clone(&slot));
        drop(slots);
        drop(retired);
        slot
    }

    fn remove(&self, id: u64) {
        let retired = self.0.lock().unwrap_or_else(|e| e.into_inner()).remove(&id);
        drop(retired);
    }
}

struct Slot {
    uri: String,
    auth: Option<ObjectStoreAuth>,
    database: Mutex<Option<Arc<Mutex<Database>>>>,
}

impl Slot {
    fn new(uri: &str, auth: Option<ObjectStoreAuth>) -> Arc<Self> {
        Arc::new(Self {
            uri: uri.to_owned(),
            auth,
            database: Mutex::default(),
        })
    }
}

pub(super) struct Pending {
    slot: Arc<Slot>,
    timeout_ms: Option<u64>,
    nested: bool,
}

impl Pending {
    pub(super) fn new(
        context: &Context,
        source: &CloudSource,
        timeout_ms: Option<u64>,
        schema: &[ColumnSpec],
        cache: Option<Arc<DatabaseCache>>,
    ) -> Result<Self, BackendError> {
        let scope = Scope::resolve(context)?;
        if let Some(cache) = &cache {
            scope.track(cache);
        }
        Self::resolve(context, source, timeout_ms, schema, &scope, cache.as_ref())
    }

    fn resolve(
        context: &Context,
        source: &CloudSource,
        timeout_ms: Option<u64>,
        schema: &[ColumnSpec],
        scope: &Scope,
        cache: Option<&Arc<DatabaseCache>>,
    ) -> Result<Self, BackendError> {
        let auth = ObjectStoreAuth::resolve(context, source).inspect_err(|_| {
            if let Some(cache) = cache {
                cache.cloud.remove(scope.id());
            }
        })?;
        let slot = match cache {
            Some(cache) => cache.cloud.select(scope.id(), &source.uri, auth),
            None => Slot::new(&source.uri, auth),
        };
        Ok(Self {
            slot,
            timeout_ms,
            nested: schema.iter().any(|column| column.data_type.is_nested()),
        })
    }

    fn connect(&self, database: Arc<Mutex<Database>>) -> Result<Session, BackendError> {
        let mut session = Session::connect_native(database, self.timeout_ms, self.nested)?;
        let connection = &mut session.connection;
        // The matching HTTPFS is auto-loaded from the static Ladybug build.
        if let Some(auth) = &self.slot.auth {
            auth.configure(connection)?;
        }
        set_bool(connection, c"http_cache_file", false)?;

        Ok(session)
    }

    fn attach(&self) -> Result<Session, BackendError> {
        let database = Arc::new(Mutex::new(Database::open(Path::new(":memory:"), false)?));
        let mut session = self.connect(database)?;
        // Escape both Cypher string delimiters. The core source parser also validates the URI.
        let escaped = self.slot.uri.replace('\\', "\\\\").replace('\'', "\\'");
        let attach = CString::new(format!("ATTACH '{escaped}' AS qw_snapshot (dbtype lbug)"))
            .map_err(|_| BackendError::RemoteConfig)?;
        command(
            &mut session.connection,
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
        // HTTPFS has mutable client and offset state. Serialize execution on
        // this attachment only. An overlapping scan gets its own attachment.
        // Arrow readers drain materialized results after this guard is released.
        let mut cached = match self.slot.database.try_lock() {
            Ok(guard) => guard,
            Err(TryLockError::WouldBlock) => {
                return Box::new(self.attach()?).execute_admitted(&cypher, params);
            }
            Err(TryLockError::Poisoned(_)) => return Err(BackendError::Open),
        };
        let session = match &*cached {
            Some(database) => self.connect(Arc::clone(database))?,
            None => {
                let session = self.attach()?;
                *cached = Some(Arc::clone(&session._database));
                session
            }
        };
        Box::new(session).execute_admitted(&cypher, params)
    }
}

pub(super) fn prepare_registration(
    context: &Context,
    source: &CloudSource,
    timeout_ms: Option<u64>,
    cache: &Arc<DatabaseCache>,
) -> Result<(GraphCatalog, Arc<Scope>), BackendError> {
    let scope = Scope::resolve(context)?;
    let pending = Pending::resolve(context, source, timeout_ms, &[], &scope, Some(cache))?;
    let mut session = pending.attach()?;
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
    if !ok {
        return Err(BackendError::Schema);
    }
    command(
        &mut session.connection,
        c"COMMIT",
        timeout_ms,
        BackendError::Schema,
    )?;
    *pending
        .slot
        .database
        .lock()
        .map_err(|_| BackendError::Open)? = Some(Arc::clone(&session._database));
    Ok((catalog, scope))
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
    use super::{Cache, Credential, Endpoint, ObjectStoreAuth, valid_region};
    use std::sync::Arc;

    #[test]
    fn reuse_requires_the_same_connection_uri_and_every_credential_field() {
        let cache = Cache::default();
        let fields = ["identity", "key", "token", "region"];
        let credential = |v: [&str; 4]| {
            Some(ObjectStoreAuth {
                credential: Credential {
                    key_id: v[0].into(),
                    secret: v[1].into(),
                    token: v[2].into(),
                    region: v[3].into(),
                },
                endpoint: Endpoint {
                    prefix: "s3",
                    host: "example.invalid".into(),
                    disable_ssl: false,
                },
            })
        };
        let uri = "s3://graphs/v1.lbdb";
        let slot = cache.select(1, uri, credential(fields));
        assert!(Arc::ptr_eq(
            &slot,
            &cache.select(1, uri, credential(fields))
        ));
        assert!(!Arc::ptr_eq(
            &slot,
            &cache.select(2, uri, credential(fields))
        ));
        for i in 0..fields.len() {
            let initial = cache.select(1, uri, credential(fields));
            let mut changed = fields;
            changed[i] = "replacement";
            assert!(!Arc::ptr_eq(
                &initial,
                &cache.select(1, uri, credential(changed))
            ));
        }
        let initial = cache.select(1, uri, credential(fields));
        let replaced = cache.select(1, "s3://graphs/v2.lbdb", credential(fields));
        assert!(!Arc::ptr_eq(&initial, &replaced));
        cache.remove(1);
        assert!(!Arc::ptr_eq(
            &replaced,
            &cache.select(1, "s3://graphs/v2.lbdb", credential(fields))
        ));
    }

    #[test]
    fn public_xet_slots_reuse_only_the_same_uri_and_connection() {
        let cache = Cache::default();
        let uri = "xet://datasets/example-owner/example-repo/0123456789abcdef0123456789abcdef01234567/graph.lbdb";
        let slot = cache.select(1, uri, None);
        assert!(Arc::ptr_eq(&slot, &cache.select(1, uri, None)));
        assert!(!Arc::ptr_eq(&slot, &cache.select(2, uri, None)));
        let replacement = uri.replace("0123456789abcdef", "fedcba9876543210");
        assert!(!Arc::ptr_eq(&slot, &cache.select(1, &replacement, None)));
    }

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
