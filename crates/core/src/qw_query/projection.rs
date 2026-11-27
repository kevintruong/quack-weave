//! Map DuckDB's requested output positions to an execution-local provider schema.
//! An opaque or budget-limited read still evaluates and validates every native
//! column, including columns the host removes from the final result.
use std::collections::HashMap;

use duckdb_neo::table_function::InitColumnData;

use super::{
    BoundRead, ColumnSpec, Context, Error, Result, ScalarType,
    runtime_watch::{self, WatchlistRoute},
};

pub(super) struct ScanProjection {
    query: Option<String>,
    schema: Option<Vec<ColumnSpec>>,
    pub(super) output_columns: Vec<usize>,
    pub(super) watchlist_route: WatchlistRoute,
}

impl ScanProjection {
    pub(super) fn new(
        context: &Context,
        bound: &BoundRead,
        columns: InitColumnData<'_>,
    ) -> Result<Self> {
        // For count(*) / SELECT 1 the pinned C API requests the first physical
        // column as its row carrier. The grammar supplies qw_row for a constant-only projection.
        let requested = (0..columns.count()?)
            .map(|position| columns.get_column_index(position))
            .collect::<Result<Vec<_>>>()?;
        if requested.iter().any(|&slot| slot >= bound.schema.len()) {
            return Err(Error::internal(
                "Graph scan received an unknown output column",
            ));
        }
        let original = |output_columns, query, watchlist_route| {
            Ok(Self {
                query,
                schema: None,
                output_columns,
                watchlist_route,
            })
        };
        // Both candidate sources are optional until this execution initializes.
        // A prepared literal plan keeps its base query when the gate is disabled.
        let watchlist_enabled = (bound.literal_candidate.is_some()
            || bound.watch.is_some()
            || bound.allows_pgq_rewrite())
            && runtime_watch::enabled(context)?;
        if watchlist_enabled && let Some(candidate) = &bound.literal_candidate {
            return original(
                requested,
                Some(candidate.clone()),
                WatchlistRoute::LiteralExact,
            );
        }
        let Some(fragment) = bound
            .fragment
            .as_ref()
            .filter(|_| bound.allows_pgq_rewrite())
        else {
            if watchlist_enabled
                && let Some(watch) = &bound.watch
                && let Some(query) =
                    watch.query(&bound.provider.backend.runtime_watch_keys(watch.column))
            {
                return original(requested, Some(query), WatchlistRoute::RuntimeExact);
            }
            return original(requested, None, WatchlistRoute::Host);
        };
        let runtime_predicate = if watchlist_enabled {
            bound.runtime_predicate()
        } else {
            None
        };
        let static_predicate = bound.static_predicate_sql()?;
        let runtime_sql = runtime_predicate
            .as_ref()
            .and_then(|exact| exact.predicate(fragment));
        let backend = &bound.provider.backend;
        let ordered_offer = backend.ordered_watchlist_limit().filter(|offer| {
            static_predicate.is_none()
                && runtime_sql.is_some()
                && runtime_predicate
                    .as_ref()
                    .is_some_and(|exact| exact.column == offer.join_column)
                && requested.contains(&offer.order_column)
                && bound.schema.get(offer.order_column).is_some_and(|col| {
                    col.data_type == ScalarType::BigInt
                        && col.name == format!("qw_col{}", offer.order_column)
                })
        });
        let bounded_suffix = match ordered_offer {
            Some(offer) if runtime_watch::ordered_limit_enabled(context)? => {
                backend.ordered_watchlist_suffix(offer.order_column, offer.limit)
            }
            _ => None,
        };
        let watchlist_route = if bounded_suffix.is_some() {
            WatchlistRoute::BoundedExact
        } else if runtime_sql.is_some() {
            WatchlistRoute::RuntimeExact
        } else {
            WatchlistRoute::Host
        };
        let predicates: Vec<_> = [static_predicate, runtime_sql]
            .into_iter()
            .flatten()
            .collect();
        if requested.iter().copied().eq(0..bound.schema.len()) && predicates.is_empty() {
            return original(requested, None, watchlist_route);
        }
        let mut query = fragment.pattern().to_owned();
        if !predicates.is_empty() {
            query.push_str(" WHERE ");
            query.push_str(&predicates.join(" AND "));
        }
        // A repeated SQL slot needs only one provider column. DuckDB's consumer
        // receives the requested ordering and multiplicity via output_columns.
        let mut positions = HashMap::new();
        let mut schema = Vec::new();
        let mut expressions = Vec::new();
        let mut output_columns = Vec::with_capacity(requested.len());
        for slot in requested {
            let position = if let Some(&existing) = positions.get(&slot) {
                existing
            } else {
                let column = &bound.schema[slot];
                let expr = fragment
                    .expr(slot)
                    .ok_or_else(|| Error::internal("Missing bound graph property"))?;
                let position = schema.len();
                schema.push(column.clone());
                expressions.push(format!("{expr} AS {}", column.name));
                positions.insert(slot, position);
                position
            };
            output_columns.push(position);
        }
        query.push_str(" RETURN ");
        query.push_str(&expressions.join(", "));
        if let Some(suffix) = bounded_suffix {
            query.push_str(&suffix);
        }
        Ok(Self {
            query: Some(query),
            schema: Some(schema),
            output_columns,
            watchlist_route,
        })
    }

    pub(super) fn query<'a>(&'a self, bound: &'a BoundRead) -> &'a str {
        self.query.as_deref().unwrap_or(&bound.cypher)
    }

    pub(super) fn schema<'a>(&'a self, bound: &'a BoundRead) -> &'a [ColumnSpec] {
        self.schema.as_deref().unwrap_or(&bound.schema)
    }
}
