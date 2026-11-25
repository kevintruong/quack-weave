use duckdb_neo::table_function::{BindInfoApi, TableGetBindInfoCallbacks};

use super::{BoundRead, Context, GraphQuery, ProviderKind, Result, ToValue};

impl TableGetBindInfoCallbacks for GraphQuery {
    fn bind_info(&self, context: &Context, bound: &BoundRead, info: BindInfoApi<'_>) -> Result<()> {
        info.set_option("qw_provider", &bound.provider.kind.name().value(context)?)?;
        let mode = match bound.fragment.as_ref() {
            None => "native",
            Some(fragment)
                if bound.cypher
                    != format!("{} RETURN {}", fragment.pattern(), fragment.projection()) =>
            {
                "literal"
            }
            Some(_)
                if bound.config.config.max_batch_bytes.is_some()
                    || bound.config.config.timeout_ms.is_some() =>
            {
                "limit"
            }
            Some(_) if !bound.allows_pgq_rewrite() => "catalog",
            Some(_) if bound.static_predicate_sql()?.is_some() => "static",
            Some(_) => "pattern",
        };
        info.set_option("qw_scan_mode", &mode.value(context)?)?;
        if bound.allows_pgq_rewrite()
            && let Some(fragment) = &bound.fragment
        {
            info.set_option("qw_match", &fragment.pattern().value(context)?)?;
            info.set_option("qw_pgq_projection", &fragment.projection().value(context)?)?;
            info.set_option(
                "qw_pattern_steps",
                &(fragment.steps() as u64).value(context)?,
            )?;
            for index in 0..bound.schema.len() {
                if let Some(expr) = fragment.expr(index) {
                    info.set_option(format!("qw_property_{index}"), &expr.value(context)?)?;
                }
            }
        }
        if bound.watch.is_some() {
            info.set_option("qw_runtime_watch", &true.value(context)?)?;
        }
        // Replanning the provider work changes batch boundaries and timing. Preserve
        // the original scan whenever the caller configured an explicit execution limit.
        let config = &bound.config.config;
        if config.max_batch_bytes.is_none() && config.timeout_ms.is_none() {
            if bound.provider.kind == ProviderKind::Relate {
                let Some(bound_rows) = bound.config.single_pattern_row_bound else {
                    return Ok(());
                };
                info.set_option("qw_single_pattern_row_bound", &bound_rows.value(context)?)?;
            }
            info.set_option(
                "qw_aggregate_generation",
                &bound.config.generation.id().value(context)?,
            )?;
        }
        Ok(())
    }
}
