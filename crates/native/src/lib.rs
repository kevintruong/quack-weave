use duckdb_neo::{Result, duckdb_entrypoint_c_api_v2, extension::Extension};

#[cfg(all(feature = "gql", not(feature = "template-compat")))]
pub mod gql;

#[cfg(not(feature = "template-compat"))]
mod ladybug;

#[cfg(not(feature = "template-compat"))]
#[duckdb_entrypoint_c_api_v2(extension_name = "quack_weave", api_version = "2.0.1")]
pub fn entrypoint(extension: &Extension) -> Result<()> {
    rusty_quack_core::register(extension)?;
    #[cfg(feature = "gql")]
    return rusty_quack_core::qw_query::register_with_gql(
        extension,
        ladybug::LadybugBackend,
        gql::parse,
    );
    #[cfg(not(feature = "gql"))]
    return rusty_quack_core::qw_query::register(extension, ladybug::LadybugBackend);
}

#[cfg(feature = "template-compat")]
#[duckdb_entrypoint_c_api_v2(extension_name = "rusty_quack", api_version = "2.0.1")]
pub fn template_entrypoint(extension: &Extension) -> Result<()> {
    rusty_quack_core::register(extension)
}
