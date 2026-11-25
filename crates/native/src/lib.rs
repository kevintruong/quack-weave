use duckdb_neo::{Result, duckdb_entrypoint_c_api_v2, extension::Extension};

#[cfg(not(feature = "template-compat"))]
use rusty_quack_core::qw_query::{
    GqlParser, GraphProvider, ProviderDescriptor, ProviderRewrite, ProviderSource, register_query,
};

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
    let ladybug = GraphProvider::new(
        ProviderDescriptor {
            id: "ladybug",
            name: "Ladybug",
            option: "qw_ladybug_config",
            source: ProviderSource::LocalFile,
            unknown_alias_error: Some("QW_CONFIG: Unknown Ladybug graph alias"),
            accepts_declared_catalog: false,
            supports_timeout: true,
            rewrite: ProviderRewrite::LabelCatalog,
        },
        ladybug::LadybugBackend::default(),
    );
    #[cfg(feature = "relate-provider")]
    let providers = vec![
        ladybug,
        GraphProvider::new(
            ProviderDescriptor {
                id: "relate",
                name: "RelateDB",
                option: "qw_relate_config",
                source: ProviderSource::LocalFile,
                unknown_alias_error: None,
                accepts_declared_catalog: true,
                supports_timeout: false,
                rewrite: ProviderRewrite::ObservedCatalog,
            },
            relate_backend::RelateBackend::default(),
        ),
    ];
    #[cfg(not(feature = "relate-provider"))]
    let providers = vec![ladybug];
    let gql_parser: Option<GqlParser> = {
        #[cfg(feature = "gql")]
        {
            Some(gql::parse)
        }
        #[cfg(not(feature = "gql"))]
        {
            None
        }
    };
    let providers = register_query(extension, providers, gql_parser)?;
    #[cfg(feature = "gql")]
    graph_entry::register(extension, providers)?;
    #[cfg(not(feature = "gql"))]
    drop(providers);
    Ok(())
}

#[cfg(feature = "template-compat")]
#[duckdb_entrypoint_c_api_v2(extension_name = "rusty_quack", api_version = "2.0.1")]
pub fn template_entrypoint(extension: &Extension) -> Result<()> {
    rusty_quack_core::register(extension)
}
