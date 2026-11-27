use std::ffi::c_void;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, Weak};

use duckdb_neo::{AsRaw, connection::Context};

use super::{BackendError, DatabaseCache};

unsafe extern "C" {
    fn qw_visit_ladybug_cloud_scope(
        context: *mut c_void,
        create: extern "C" fn() -> *const c_void,
        drop: unsafe extern "C" fn(*const c_void),
        output: *mut c_void,
        visit: unsafe extern "C" fn(*mut c_void, *const c_void),
    ) -> bool;
}

static NEXT_SCOPE: AtomicU64 = AtomicU64::new(1);

pub(in crate::ladybug) struct Scope {
    id: u64,
    caches: Mutex<Vec<Weak<DatabaseCache>>>,
}

impl Scope {
    pub(super) fn resolve(context: &Context) -> Result<Arc<Self>, BackendError> {
        let mut scope = None::<Arc<Self>>;
        let found = unsafe {
            qw_visit_ladybug_cloud_scope(
                context.get_raw().cast(),
                create_scope,
                drop_scope,
                (&raw mut scope).cast(),
                copy_scope,
            )
        };
        if !found {
            return Err(BackendError::Open);
        }
        scope.ok_or(BackendError::Open)
    }

    pub(super) fn id(&self) -> u64 {
        self.id
    }

    pub(in crate::ladybug) fn track(&self, cache: &Arc<DatabaseCache>) {
        let mut caches = self.caches.lock().unwrap_or_else(|err| err.into_inner());
        caches.retain(|cache| cache.strong_count() != 0);
        let cache = Arc::downgrade(cache);
        if !caches.iter().any(|tracked| tracked.ptr_eq(&cache)) {
            caches.push(cache);
        }
    }
}

impl Drop for Scope {
    fn drop(&mut self) {
        // A replaced generation can already be gone. Active readers retain their own attachment.
        let caches = self.caches.get_mut().unwrap_or_else(|err| err.into_inner());
        for cache in caches.iter().filter_map(Weak::upgrade) {
            cache.cloud.remove(self.id);
        }
    }
}

extern "C" fn create_scope() -> *const c_void {
    let Ok(id) =
        NEXT_SCOPE.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |id| id.checked_add(1))
    else {
        return std::ptr::null();
    };
    Arc::into_raw(Arc::new(Scope {
        id,
        caches: Mutex::new(Vec::new()),
    }))
    .cast()
}

unsafe extern "C" fn drop_scope(raw: *const c_void) {
    // The DuckDB ClientContext state owns the reference returned by create_scope.
    unsafe { drop(Arc::from_raw(raw.cast::<Scope>())) };
}

unsafe extern "C" fn copy_scope(output: *mut c_void, raw: *const c_void) {
    let raw = raw.cast::<Scope>();
    // The C++ visitor holds the ClientContext state until this callback returns.
    unsafe {
        Arc::increment_strong_count(raw);
        *output.cast::<Option<Arc<Scope>>>() = Some(Arc::from_raw(raw));
    }
}
