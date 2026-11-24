//! Transport graph parameters as typed DuckDB values. Query text is bound separately.
use duckdb_neo::{
    DuckDBType, FromValue, Result, connection::Context, enums::LogicalTypeID, error::Error,
    value::Value,
};

#[derive(Debug)]
pub enum GraphParameter {
    Null,
    Boolean(bool),
    Integer(i64),
    Double(f64),
    Text(String),
}

pub(super) fn from_struct(
    context: &Context,
    bindings: &Value,
) -> Result<Vec<(String, GraphParameter)>> {
    let ty = bindings.logical_type()?;
    if bindings.is_null()? || ty.id()? != LogicalTypeID::Struct {
        return Err(Error::invalid_input(
            "QW_ARGUMENT: Expected named graph parameter values",
        ));
    }
    let mut params = Vec::new();
    for index in 0..bindings.child_count()? {
        let (name, _) = ty.get_param(index)?;
        if !super::is_identifier(name) {
            return Err(Error::invalid_input(
                "QW_ARGUMENT: Unsupported graph parameter name",
            ));
        }
        let child = bindings.get_child(index)?;
        let value = if child.is_null()? {
            GraphParameter::Null
        } else {
            use LogicalTypeID as Id;
            match child.logical_type()?.id()? {
                Id::Boolean => GraphParameter::Boolean(bool::from_value(&child)?.unwrap()),
                Id::TinyInt
                | Id::SmallInt
                | Id::Integer
                | Id::BigInt
                | Id::UTinyInt
                | Id::USmallInt
                | Id::UInteger => {
                    let signed = child.cast(context, &i64::logical_type(context)?)?;
                    GraphParameter::Integer(i64::from_value(&signed)?.unwrap())
                }
                Id::Float | Id::Double => {
                    let double = child.cast(context, &f64::logical_type(context)?)?;
                    GraphParameter::Double(f64::from_value(&double)?.unwrap())
                }
                Id::Varchar => GraphParameter::Text(String::from_value(&child)?.unwrap()),
                _ => {
                    return Err(Error::invalid_input(
                        "QW_ARGUMENT: Unsupported graph parameter type",
                    ));
                }
            }
        };
        params.push((name.to_owned(), value));
    }
    Ok(params)
}
