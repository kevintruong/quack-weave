//! Map DuckDB's requested output positions to an execution-local provider schema.
//! An opaque or budget-limited read still evaluates and validates every native
//! column, including columns the host removes from the final result.
use std::collections::HashMap;

use duckdb_neo::table_function::InitColumnData;

use super::{BoundRead, ColumnSpec, Error, Result};

pub(super) struct ScanProjection {
    query: Option<String>,
    schema: Option<Vec<ColumnSpec>>,
    pub(super) output_columns: Vec<usize>,
}

impl ScanProjection {
    pub(super) fn new(bound: &BoundRead, columns: InitColumnData<'_>) -> Result<Self> {
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
        let original = |output_columns| Self {
            query: bound.watch.as_ref().and_then(|watch| {
                watch.query(&bound.provider.backend.runtime_watch_keys(watch.column))
            }),
            schema: None,
            output_columns,
        };
        let Some(fragment) = bound
            .fragment
            .as_ref()
            .filter(|_| bound.allows_pgq_rewrite())
        else {
            return Ok(original(requested));
        };
        // Legacy literal watchlists can bind an already filtered native query.
        // Preserve that read instead of replacing its existing predicate.
        let base = format!("{} RETURN {}", fragment.pattern(), fragment.projection());
        if base != bound.cypher || bound.watch.is_some() {
            return Ok(original(requested));
        }
        if requested.iter().copied().eq(0..bound.schema.len()) {
            return Ok(Self {
                query: None,
                schema: None,
                output_columns: requested,
            });
        }
        let mut query = fragment.pattern().to_owned();
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
        Ok(Self {
            query: Some(query),
            schema: Some(schema),
            output_columns,
        })
    }

    pub(super) fn query<'a>(&'a self, bound: &'a BoundRead) -> &'a str {
        self.query.as_deref().unwrap_or(&bound.cypher)
    }

    pub(super) fn schema<'a>(&'a self, bound: &'a BoundRead) -> &'a [ColumnSpec] {
        self.schema.as_deref().unwrap_or(&bound.schema)
    }
}
