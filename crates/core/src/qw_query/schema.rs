//! The explicit scalar schema shared by native and browser graph queries.

use std::collections::HashSet;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ScalarType {
    Boolean,
    BigInt,
    Double,
    Varchar,
    Struct(Vec<ColumnSpec>),
    List(Box<ScalarType>),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ColumnSpec {
    pub name: String,
    pub data_type: ScalarType,
}

pub(super) fn is_identifier(text: &str) -> bool {
    let mut bytes = text.bytes();
    bytes
        .next()
        .is_some_and(|byte| byte.is_ascii_alphabetic() || byte == b'_')
        && bytes.all(|byte| byte.is_ascii_alphanumeric() || byte == b'_')
}

pub(super) fn parse_schema(schema: &str) -> Result<Vec<ColumnSpec>, &'static str> {
    const INVALID: &str = "QW_ARGUMENT: Expected comma-separated schema entries using BOOLEAN, BIGINT, DOUBLE or VARCHAR";
    let mut seen = HashSet::new();
    schema
        .split(',')
        .map(|entry| {
            let mut parts = entry.split_ascii_whitespace();
            let name = parts.next().ok_or(INVALID)?;
            let type_name = parts.next().ok_or(INVALID)?;
            if !is_identifier(name) || parts.next().is_some() {
                return Err(INVALID);
            }
            if !seen.insert(name.to_ascii_lowercase()) {
                return Err("QW_ARGUMENT: Duplicate result column in schema");
            }
            let data_type = match type_name.to_ascii_uppercase().as_str() {
                "BOOLEAN" => ScalarType::Boolean,
                "BIGINT" => ScalarType::BigInt,
                "DOUBLE" => ScalarType::Double,
                "VARCHAR" => ScalarType::Varchar,
                _ => return Err(INVALID),
            };
            Ok(ColumnSpec {
                name: name.to_owned(),
                data_type,
            })
        })
        .collect()
}
