use std::ffi::c_void;

use duckdb_neo::{AsRaw, Result, connection::HasFactory, error::Error, extension::Extension};

unsafe extern "C" {
    fn qw_register_neo4j_secret(factory: *mut c_void) -> bool;
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
