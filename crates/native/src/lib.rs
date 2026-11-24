use duckdb_neo::{Result, duckdb_entrypoint_c_api_v2, extension::Extension};

#[cfg(all(feature = "gql", not(feature = "template-compat")))]
pub mod gql;

#[cfg(all(feature = "gql", not(feature = "template-compat")))]
mod graph_entry;

#[cfg(not(feature = "template-compat"))]
mod batch_budget;

#[cfg(not(feature = "template-compat"))]
mod ladybug;

#[cfg(all(feature = "relate-provider", not(feature = "template-compat")))]
mod relate_backend;

#[cfg(all(test, not(feature = "template-compat")))]
mod test_observation;

#[cfg(not(feature = "template-compat"))]
#[duckdb_entrypoint_c_api_v2(extension_name = "quack_weave", api_version = "2.0.1")]
pub fn entrypoint(extension: &Extension) -> Result<()> {
    rusty_quack_core::register(extension)?;
    #[cfg(feature = "gql")]
    {
        #[cfg(feature = "relate-provider")]
        rusty_quack_core::qw_query::register_with_relate(
            extension,
            ladybug::LadybugBackend::default(),
            relate_backend::RelateBackend::default(),
            gql::parse,
        )?;
        #[cfg(not(feature = "relate-provider"))]
        rusty_quack_core::qw_query::register_with_gql(
            extension,
            ladybug::LadybugBackend::default(),
            gql::parse,
        )?;
        return graph_entry::register(extension);
    }
    #[cfg(not(feature = "gql"))]
    return rusty_quack_core::qw_query::register(extension, ladybug::LadybugBackend::default());
}

#[cfg(feature = "template-compat")]
#[duckdb_entrypoint_c_api_v2(extension_name = "rusty_quack", api_version = "2.0.1")]
pub fn template_entrypoint(extension: &Extension) -> Result<()> {
    rusty_quack_core::register(extension)
}
