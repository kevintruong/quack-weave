//! Admit only row-producing reads and exclude procedures, external input, and session control.
use relate_parser::{
    Clause, Expr, ExprEdge, GroupBySpec, LabelExpr, OrderByItem, PatternElement, PreambleMode,
    ReturnItem, Statement,
};
use rusty_quack_core::qw_query::BackendError::{self, Admission};

// The pinned Relate parser uses the same stack budget as its engine worker.
const READ_PARSER_STACK_BYTES: usize = 64 * 1024 * 1024;
#[cfg(feature = "relate-provider")]
const _: () = assert!(READ_PARSER_STACK_BYTES == relate::QUERY_WORKER_STACK_BYTES);

/// Parse, visit and drop the recursive AST on a worker with the pinned stack budget.
pub(crate) fn admit<T: Send>(
    text: &str,
    inspect: impl FnOnce(&Statement) -> Result<T, BackendError> + Send,
) -> Result<T, BackendError> {
    std::thread::scope(|scope| {
        std::thread::Builder::new()
            .name("qw-cypher-parser".into())
            .stack_size(READ_PARSER_STACK_BYTES)
            .spawn_scoped(scope, || inspect(&read_statement(text)?))
            .map_err(|_| BackendError::Execution)?
            .join()
            .map_err(|_| Admission)?
    })
}

fn read_statement(text: &str) -> Result<Statement, BackendError> {
    let stmt = relate_parser::parse(text).map_err(|_| Admission)?;
    if stmt.preamble != PreambleMode::Execute
        || stmt.union.is_some()
        || stmt.next.is_some()
        || !stmt.definitions.is_empty()
        || !matches!(stmt.clauses.last(), Some(Clause::Return(_)))
    {
        return Err(Admission);
    }
    for clause in &stmt.clauses {
        match clause {
            Clause::Match(m) if m.search.is_none() => {
                m.where_expr.iter().try_for_each(expression)?;
                for path in &m.pattern {
                    path.where_expr.iter().try_for_each(expression)?;
                    for elem in &path.elements {
                        let (label, properties, param, predicate) = match elem {
                            PatternElement::Node(n) => (
                                &n.label_expr,
                                &n.properties,
                                &n.properties_param,
                                &n.where_expr,
                            ),
                            PatternElement::Relationship(r) => (
                                &r.type_expr,
                                &r.properties,
                                &r.properties_param,
                                &r.where_expr,
                            ),
                            PatternElement::Quantified(_) => return Err(Admission),
                        };
                        if label.as_ref().is_some_and(|l| l.contains_dynamic()) {
                            return Err(Admission);
                        }
                        for (_, value) in properties {
                            expression(value)?;
                        }
                        param.iter().chain(predicate).try_for_each(expression)?;
                    }
                }
            }
            Clause::Unwind(u) => expression(&u.expr)?,
            Clause::Return(r) => projected(&r.items, &r.order_by, &r.group_by, &r.skip, &r.limit)?,
            Clause::With(w) => {
                projected(&w.items, &w.order_by, &w.group_by, &w.skip, &w.limit)?;
                w.where_expr.iter().try_for_each(expression)?;
            }
            _ => return Err(Admission),
        }
    }
    Ok(stmt)
}

fn projected(
    items: &[ReturnItem],
    order: &[OrderByItem],
    group: &Option<GroupBySpec>,
    skip: &Option<Expr>,
    limit: &Option<Expr>,
) -> Result<(), BackendError> {
    for item in items {
        expression(&item.expr)?;
    }
    for item in order {
        expression(&item.expr)?;
    }
    if let Some(GroupBySpec::Keys(keys)) = group {
        keys.iter().try_for_each(expression)?;
    }
    skip.iter().chain(limit).try_for_each(expression)
}

fn expression(expr: &Expr) -> Result<(), BackendError> {
    if let Expr::FunctionCall(f) = expr {
        // Only built-in, data-local scalar and aggregate functions are callable.
        match f.name.to_string().to_ascii_lowercase().as_str() {
            "count" | "sum" | "avg" | "min" | "max" | "collect" | "coalesce" | "size"
            | "length" | "tointeger" | "tofloat" | "tostring" | "toboolean" | "tolower"
            | "toupper" | "trim" | "substring" | "abs" | "round" | "ceil" | "floor" | "labels"
            | "type" | "id" | "elementid" | "head" | "last" | "range" => (),
            _ => return Err(Admission),
        }
    }
    expr.try_for_each_edge(|edge| match edge {
        ExprEdge::Expr(e) => expression(e),
        ExprEdge::Label(LabelExpr::Label(_)) => Ok(()),
        // Subqueries or pattern expressions can introduce additional clauses and scopes.
        _ => Err(Admission),
    })
}
