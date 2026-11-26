use std::{
    ffi::c_void,
    panic::{AssertUnwindSafe, catch_unwind},
    slice, str,
};

use duckdb_neo::{
    AsRaw, Result,
    connection::{Context, HasFactory},
    error::Error,
    extension::Extension,
};

#[repr(C)]
struct SecretText {
    data: *const u8,
    size: usize,
}

type SecretVisitor = unsafe extern "C" fn(*mut c_void, SecretText, SecretText, SecretText);

unsafe extern "C" {
    fn qw_register_neo4j_secret(factory: *mut c_void) -> bool;
    fn qw_visit_neo4j_secret(
        context: *mut c_void,
        name: *const u8,
        name_size: usize,
        state: *mut c_void,
        visit: SecretVisitor,
    ) -> bool;
}

pub(crate) fn register(extension: &Extension) -> Result<()> {
    // The factory is borrowed for this call. DuckDB owns the installed secret type and provider.
    let registered = unsafe { qw_register_neo4j_secret(extension.factory()?.get_raw().cast()) };
    if !registered {
        return Err(Error::invalid_input(
            "QW_CONFIG: Could not register the Neo4j credential secret",
        ));
    }
    Ok(())
}

pub(crate) fn with_credentials<F, T>(context: &Context, name: &str, consume: F) -> Option<T>
where
    F: FnOnce(&str, &str, &str) -> Option<T>,
{
    let mut state = (Some(consume), None::<T>);
    // Both the executing context and the callback state are borrowed for the call.
    let found = unsafe {
        qw_visit_neo4j_secret(
            context.get_raw().cast(),
            name.as_ptr(),
            name.len(),
            (&raw mut state).cast(),
            visit_credentials::<F, T>,
        )
    };
    if found { state.1 } else { None }
}

unsafe extern "C" fn visit_credentials<F, T>(
    state: *mut c_void,
    origin: SecretText,
    username: SecretText,
    password: SecretText,
) where
    F: FnOnce(&str, &str, &str) -> Option<T>,
{
    // The bridge supplies a live state pointer and three string views for this invocation only.
    let (consume, result) = unsafe { &mut *state.cast::<(Option<F>, Option<T>)>() };
    *result = catch_unwind(AssertUnwindSafe(|| {
        let consume = consume.take()?;
        let origin = unsafe { origin.as_str() }?;
        let username = unsafe { username.as_str() }?;
        let password = unsafe { password.as_str() }?;
        consume(origin, username, password)
    }))
    .ok()
    .flatten();
}

impl SecretText {
    /// The pointer has to remain valid for this borrow. The C++ visitor owns its source.
    unsafe fn as_str(&self) -> Option<&str> {
        let bytes = unsafe { slice::from_raw_parts(self.data, self.size) };
        str::from_utf8(bytes).ok()
    }
}
