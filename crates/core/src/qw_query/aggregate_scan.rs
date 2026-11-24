use duckdb_neo::table_function::{BindInfoApi, TableGetBindInfoCallbacks};

use super::{BoundRead, Context, GraphQuery, ProviderKind, Result, ToValue};

impl TableGetBindInfoCallbacks for GraphQuery {
    fn bind_info(&self, context: &Context, bound: &BoundRead, info: BindInfoApi<'_>) -> Result<()> {
        if bound.watch.is_some() {
            info.set_option("qw_runtime_watch", &true.value(context)?)?;
        }
        // Replanning the provider work changes batch boundaries and timing. Preserve
        // the original scan whenever the caller configured an explicit execution limit.
        let config = &bound.config.config;
        if bound.provider.kind == ProviderKind::Ladybug
            && config.max_batch_bytes.is_none()
            && config.timeout_ms.is_none()
        {
            info.set_option(
                "qw_aggregate_generation",
                &bound.config.generation.id().value(context)?,
            )?;
        }
        Ok(())
    }
}
