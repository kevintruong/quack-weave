//! Optional graph prefilters offered by DuckDB for bound, structured scans.
//! DuckDB keeps the original expressions (including its NULL and join semantics).
use duckdb_neo::{
    Result,
    connection::Context,
    error::Error,
    expression::{Expression, ExpressionType},
    logical_type::LogicalTypeID,
    table_function::{PushdownData, TableFilterPushdownCallbacks},
};

use super::{BoundRead, GraphFragment, GraphQuery, GraphQueryKind, MAX_KEYS, ScalarType};

impl BoundRead {
    pub(super) fn static_predicate_sql(&self) -> Result<Option<String>> {
        self.static_predicate
            .lock()
            .map(|predicate| predicate.clone())
            .map_err(|_| Error::internal("QW_QUERY: Graph filter state unavailable"))
    }
}

impl TableFilterPushdownCallbacks for GraphQuery {
    fn pushdown_filter(
        &self,
        _: &Context,
        bound: &BoundRead,
        offered: PushdownData<'_>,
    ) -> Result<()> {
        // Legacy filtered calls have their own provider predicate. Never
        // replace their source text or trust an opaque native return list.
        if self.kind != GraphQueryKind::InferredSchema || !bound.allows_pgq_rewrite() {
            return Ok(());
        }
        let Some(fragment) = &bound.fragment else {
            return Ok(());
        };
        let mut predicates = Vec::new();
        for i in 0..offered.filter_count()? {
            if let Some(sql) = translate(&offered.filter(i)?, &offered, bound, fragment)? {
                predicates.push(sql);
            }
        }
        if !predicates.is_empty() {
            // Each offer is a conjunction. Keeping just this set is sufficient
            // since all offered predicates remain in the physical SQL plan.
            *bound
                .static_predicate
                .lock()
                .map_err(|_| Error::internal("QW_QUERY: Graph filter state unavailable"))? =
                Some(predicates.join(" AND "));
        }
        Ok(())
    }
}

fn translate(
    expr: &Expression<'_>,
    offered: &PushdownData<'_>,
    bound: &BoundRead,
    fragment: &GraphFragment,
) -> Result<Option<String>> {
    let count = expr.child_count()?;
    let (column, values) = match expr.expression_type()? {
        ExpressionType::CompareEqual if count == 2 => {
            let (a, b) = (expr.child(0)?, expr.child(1)?);
            if a.expression_type()? == ExpressionType::BoundColumnRef {
                (a, vec![b])
            } else {
                (b, vec![a])
            }
        }
        ExpressionType::CompareIn if (2..=MAX_KEYS + 1).contains(&count) => {
            let mut args = expr.children()?.into_iter();
            (args.next().expect("IN has a left operand"), args.collect())
        }
        _ => return Ok(None),
    };
    if column.expression_type()? != ExpressionType::BoundColumnRef
        || column.return_type()?.id()? != LogicalTypeID::BigInt
    {
        return Ok(None);
    }
    let index = offered.get_column_index(column.reference_index()?)?;
    if !bound
        .schema
        .get(index)
        .is_some_and(|s| s.data_type == ScalarType::BigInt)
    {
        return Ok(None);
    }
    let Some(property) = fragment.property(index) else {
        return Ok(None);
    };
    let mut literals = Vec::with_capacity(values.len());
    for value in values {
        if value.expression_type()? != ExpressionType::ValueConstant
            || value.return_type()?.id()? != LogicalTypeID::BigInt
        {
            return Ok(None);
        }
        let Some(value) = value.get_constant_value()?.get::<i64>()? else {
            return Ok(None);
        };
        literals.push(value.to_string());
    }
    let name = format!("{}.{}", property.variable, property.field);
    Ok(Some(if literals.len() == 1 {
        format!("{name} = {}", literals[0])
    } else {
        format!("{name} IN [{}]", literals.join(","))
    }))
}
