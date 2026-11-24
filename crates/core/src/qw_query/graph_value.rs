//! Nested graph results keep Ladybug's field names, native property types and list order.
use duckdb_neo::{
    Parameters, QueryParameter, connection::FFILink, logical_type::LogicalTypeID,
    value::ValueInput, vector::Unknown,
};

use super::*;

impl ScalarType {
    pub fn is_nested(&self) -> bool {
        matches!(self, Self::Struct(_) | Self::List(_))
    }

    pub(super) fn nested_type(&self, context: &Context) -> Result<LogicalType> {
        match self {
            Self::List(child) => {
                let ty = child.logical_type(context)?;
                let value = Value::from_logical_type(context, &ty)?;
                LogicalType::create_from_id(
                    context,
                    LogicalTypeID::List,
                    Parameters::positional(&[&value]),
                )
            }
            Self::Struct(fields) => {
                let values = fields
                    .iter()
                    .map(|f| Value::from_logical_type(context, &f.data_type.logical_type(context)?))
                    .collect::<Result<Vec<_>>>()?;
                let parameters = fields
                    .iter()
                    .zip(&values)
                    .map(|(f, v)| (f.name.as_str(), v as &dyn QueryParameter))
                    .collect::<Vec<_>>();
                LogicalType::create_from_id(
                    context,
                    LogicalTypeID::Struct,
                    Parameters::named(&parameters),
                )
            }
            _ => Err(Error::internal("Expected a nested result type")),
        }
    }
}

#[derive(Debug)]
pub struct GraphColumn {
    pub ty: Arc<ScalarType>,
    pub rows: Vec<GraphValue>,
}

#[derive(Debug)]
pub enum GraphValue {
    Null,
    Boolean(bool),
    BigInt(i64),
    Double(f64),
    Varchar(String),
    Children(Vec<GraphValue>),
}

impl GraphValue {
    fn value(&self, ctx: &Context, ty: &ScalarType) -> Result<Value> {
        match (self, ty) {
            (Self::Null, ty) => Value::null(ctx, &ty.logical_type(ctx)?),
            (Self::Boolean(v), ScalarType::Boolean) => ctx.create_value(ValueInput::Bool(*v)),
            (Self::BigInt(v), ScalarType::BigInt) => ctx.create_value(ValueInput::BigInt(*v)),
            (Self::Double(v), ScalarType::Double) => ctx.create_value(ValueInput::Double(*v)),
            (Self::Varchar(v), ScalarType::Varchar) => ctx.create_value(ValueInput::Varchar(v)),
            (Self::Children(items), ScalarType::List(child)) => {
                let children = items
                    .iter()
                    .map(|v| v.value(ctx, child))
                    .collect::<Result<Vec<_>>>()?;
                ctx.create_value(ValueInput::List {
                    child_type: &child.logical_type(ctx)?,
                    children: &children,
                })
            }
            (Self::Children(items), ScalarType::Struct(fields)) if items.len() == fields.len() => {
                let names = fields.iter().map(|v| v.name.as_str()).collect::<Vec<_>>();
                let children = items
                    .iter()
                    .zip(fields)
                    .map(|(v, f)| v.value(ctx, &f.data_type))
                    .collect::<Result<Vec<_>>>()?;
                ctx.create_value(ValueInput::Struct {
                    names: &names,
                    children: &children,
                })
            }
            _ => Err(Error::internal("Graph value disagrees with its bound type")),
        }
    }
}

impl GraphColumn {
    pub(super) fn write(
        &self,
        ctx: &Context,
        output: &mut DataChunk<'_>,
        column: usize,
    ) -> Result<()> {
        let mut vector = output.get_vector_at_mut::<Unknown>(column)?;
        vector.set_size(self.rows.len())?;
        for (row, item) in self.rows.iter().enumerate() {
            vector.write_value_slow(row, &item.value(ctx, &self.ty)?)?;
        }
        Ok(())
    }
}
