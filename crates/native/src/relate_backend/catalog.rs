//! Relate's property catalog is inferred from stored values. A property with
//! inconsistent or non-scalar types has no static DuckDB projection.
use std::collections::{BTreeMap, HashSet};

use relate::{Connection, Value};
use relate_parser::{Clause, Expr, LabelExpr, LiteralValue, PatternElement, ReturnItem, Statement};

use super::{BackendError, ColumnSpec, GraphCatalog, ScalarType};

const NODE_PROPERTIES: &str = "CALL db.schema.nodeTypeProperties() \
    YIELD nodeLabels, propertyName, propertyTypes RETURN nodeLabels, propertyName, propertyTypes";
const EDGE_PROPERTIES: &str = "CALL db.schema.relTypeProperties() \
    YIELD relType, propertyName, propertyTypes RETURN relType, propertyName, propertyTypes";

/// Global node and edge populations from the same frozen snapshot used for
/// discovered types. Reuse these two counts for both costing and the SUM bound.
pub(super) fn populations(connection: &mut Connection) -> Option<(u64, u64)> {
    let mut count = |query| {
        let result = connection.query(query).ok()?;
        let [row] = result.rows.as_slice() else {
            return None;
        };
        let [Value::Int(n)] = row.as_slice() else {
            return None;
        };
        u64::try_from(*n).ok()
    };
    Some((
        count("MATCH (n) RETURN count(*) AS n")?,
        count("MATCH ()-[r]->() RETURN count(*) AS n")?,
    ))
}

pub(super) fn discover(connection: &mut Connection) -> Result<GraphCatalog, BackendError> {
    let mut labels: BTreeMap<String, BTreeMap<String, String>> = BTreeMap::new();
    for (kind, query) in [("node", NODE_PROPERTIES), ("relationship", EDGE_PROPERTIES)] {
        let result = connection.query(query).map_err(|_| BackendError::Open)?;
        for row in &result.rows {
            let [category, property, Value::List(types)] = row.as_slice() else {
                return Err(BackendError::Schema);
            };
            let names: Vec<&str> = match category {
                Value::List(names) => names
                    .iter()
                    .map(|v| match v {
                        Value::String(name) => Ok(name.as_ref()),
                        _ => Err(BackendError::Schema),
                    })
                    .collect::<Result<_, _>>()?,
                Value::String(rel) => vec![
                    rel.strip_prefix("[:")
                        .and_then(|s| s.strip_suffix(']'))
                        .ok_or(BackendError::Schema)?,
                ],
                _ => return Err(BackendError::Schema),
            };
            let ty = match types.as_slice() {
                [Value::String(ty)] => match ty.trim_end_matches(" NOT NULL") {
                    "BOOLEAN" => "BOOL",
                    "INTEGER" => "INT64",
                    "FLOAT" => "DOUBLE",
                    "STRING" => "STRING",
                    _ => "UNSUPPORTED",
                },
                _ => "UNSUPPORTED",
            };
            for name in names {
                let fields = labels.entry(format!("{kind}:{name}")).or_default();
                match property {
                    Value::String(property) => {
                        let found = fields
                            .entry(property.to_string())
                            .or_insert_with(|| ty.to_owned());
                        if found != ty {
                            *found = "UNSUPPORTED".to_owned();
                        }
                    }
                    Value::Null => (),
                    _ => return Err(BackendError::Schema),
                }
            }
        }
    }
    Ok(labels
        .into_iter()
        .map(|(name, fields)| (name, fields.into_iter().collect()))
        .collect())
}

pub(super) fn projection(
    catalog: &GraphCatalog,
    stmt: &Statement,
) -> Result<Vec<ColumnSpec>, BackendError> {
    let Some((Clause::Return(ret), reads)) = stmt.clauses.split_last() else {
        return Err(BackendError::Schema);
    };
    // Configuration accepts plain identifiers. Discovered keys include a colon
    // so node labels and relationship types keep their native namespaces.
    let discovered = catalog.keys().next().is_some_and(|key| key.contains(':'));
    let mut bindings = BTreeMap::new();
    for read in reads {
        let Clause::Match(m) = read else {
            return Err(BackendError::Schema);
        };
        for element in m.pattern.iter().flat_map(|p| &p.elements) {
            let (kind, variable, label) = match element {
                PatternElement::Node(n) => ("node", &n.variable, &n.label_expr),
                PatternElement::Relationship(r) if !r.is_variable_length() => {
                    ("relationship", &r.variable, &r.type_expr)
                }
                _ => continue,
            };
            let (Some(variable), Some(label)) = (variable, label) else {
                continue;
            };
            let LabelExpr::Label(label) = label else {
                return Err(BackendError::Schema);
            };
            let key = if discovered {
                format!("{kind}:{label}")
            } else {
                label.to_string()
            };
            if bindings.get(variable).is_some_and(|other| other != &key) {
                return Err(BackendError::Schema);
            }
            bindings.insert(variable, key);
        }
    }
    let mut names = HashSet::new();
    ret.items
        .iter()
        .map(|item| {
            let name = column_name(item).ok_or(BackendError::Schema)?;
            if !names.insert(name.to_ascii_lowercase()) || item.all {
                return Err(BackendError::Schema);
            }
            let ty = match &item.expr {
                Expr::Property(p) => {
                    let Expr::Variable(v) = &p.expr else {
                        return Err(BackendError::Schema);
                    };
                    let label = bindings.get(v).ok_or(BackendError::Schema)?;
                    let fields = catalog.get(label).ok_or(BackendError::Schema)?;
                    let (_, ty) = p
                        .property
                        .with_str(|prop| fields.iter().find(|(k, _)| k == prop))
                        .ok_or(BackendError::Schema)?;
                    match ty.as_str() {
                        "BOOL" => ScalarType::Boolean,
                        "INT64" => ScalarType::BigInt,
                        "DOUBLE" => ScalarType::Double,
                        "STRING" => ScalarType::Varchar,
                        _ => return Err(BackendError::Schema),
                    }
                }
                Expr::Literal(LiteralValue::Bool(_)) => ScalarType::Boolean,
                Expr::Literal(LiteralValue::Integer(_)) | Expr::CountStar => ScalarType::BigInt,
                Expr::Literal(LiteralValue::Float(_)) => ScalarType::Double,
                Expr::Literal(LiteralValue::String(_)) => ScalarType::Varchar,
                Expr::FunctionCall(f) if f.name.with_str(|n| n.eq_ignore_ascii_case("count")) => {
                    ScalarType::BigInt
                }
                _ => return Err(BackendError::Schema),
            };
            Ok(ColumnSpec {
                name,
                data_type: ty,
            })
        })
        .collect()
}

// The GQL emitter quotes each identifier. Its public unaliased column name
// is variable.property, while Relate uses the authored expression including quotes.
pub(super) fn column_name(item: &ReturnItem) -> Option<String> {
    if let Some(alias) = &item.alias {
        return Some(alias.to_string());
    }
    if let Expr::Property(p) = &item.expr
        && let Expr::Variable(v) = &p.expr
    {
        return Some(format!("{v}.{}", p.property));
    }
    item.source_text.clone()
}
