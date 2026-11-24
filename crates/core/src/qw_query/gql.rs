use std::{collections::HashSet, fmt::Write};

use duckdb_neo::{Result, error::Error};

use crate::gql::{
    Comparison, Literal, Location, NodePattern, ParseError, ParseErrorKind, ParsedRead, Property,
};

use super::is_identifier;

pub type GqlParser = fn(&str) -> std::result::Result<ParsedRead, ParseError>;

/// Compile one supported GQL read to the Cypher admitted by the selected backend.
pub fn compile_gql_query(query: &str, parser: Option<GqlParser>) -> Result<String> {
    let parser = parser.ok_or_else(|| frontend_error(ParseErrorKind::Unavailable, None))?;
    let parsed = parser(query).map_err(|error| frontend_error(error.kind, error.location))?;
    lower(&parsed)
}

fn frontend_error(kind: ParseErrorKind, location: Option<Location>) -> Error {
    let message = match kind {
        ParseErrorKind::Syntax => "QW_GQL_PARSE: Invalid GQL syntax",
        ParseErrorKind::Unsupported => {
            "QW_GQL_SUBSET: Expected one fixed directed MATCH with aliased property projections and optional WHERE or FILTER"
        }
        ParseErrorKind::Limit => "QW_GQL_PARSE: GQL input exceeds parser limits",
        ParseErrorKind::Internal => "QW_GQL_PARSE: GQL frontend could not parse the query",
        ParseErrorKind::Unavailable => "QW_GQL_UNAVAILABLE: This build has no GQL frontend",
    };
    input_error(message, location)
}

fn input_error(message: &str, location: Option<Location>) -> Error {
    match location {
        Some(Location { line, column }) => Error::invalid_input(format!(
            "{message} at line {line}, column {}",
            column.saturating_add(1)
        )),
        None => Error::invalid_input(message),
    }
}

fn lower(read: &ParsedRead) -> Result<String> {
    if read.projections.is_empty() {
        return Err(frontend_error(ParseErrorKind::Unsupported, None));
    }

    let mut cypher = String::from("MATCH ");
    if let Some(path) = &read.path_variable {
        if path.eq_ignore_ascii_case(&read.left.variable)
            || read
                .right
                .as_ref()
                .is_some_and(|right| path.eq_ignore_ascii_case(&right.variable))
            || read
                .relationship_variable
                .as_ref()
                .is_some_and(|edge| path.eq_ignore_ascii_case(edge))
        {
            return Err(input_error(
                "QW_GQL_SUBSET: Conflicting path variable",
                None,
            ));
        }
        identifier(&mut cypher, path, None)?;
        cypher.push_str(" = ");
    }
    node(&mut cypher, &read.left)?;
    if let Some(right) = &read.right {
        if read.left.variable != right.variable
            && read.left.variable.eq_ignore_ascii_case(&right.variable)
        {
            return Err(input_error(
                "QW_GQL_SUBSET: Matched variables must not differ only by case",
                Some(right.variable_span.location),
            ));
        }
        cypher.push_str("-[");
        if let Some(variable) = &read.relationship_variable {
            if variable.eq_ignore_ascii_case(&read.left.variable)
                || variable.eq_ignore_ascii_case(&right.variable)
            {
                return Err(input_error(
                    "QW_GQL_SUBSET: Conflicting relationship variable",
                    None,
                ));
            }
            identifier(&mut cypher, variable, None)?;
        }
        cypher.push(':');
        identifier(&mut cypher, &read.relationship_label, None)?;
        cypher.push_str("]->");
        node(&mut cypher, right)?;
    }

    // With exactly one fixed MATCH, both supported predicate forms filter the same bindings.
    if let Some(predicate) = &read.predicate {
        cypher.push_str(" WHERE ");
        property(&mut cypher, read, &predicate.property)?;
        cypher.push_str(match predicate.comparison {
            Comparison::Eq => " = ",
            Comparison::Ne => " <> ",
            Comparison::Lt => " < ",
            Comparison::Le => " <= ",
            Comparison::Gt => " > ",
            Comparison::Ge => " >= ",
        });
        literal(&mut cypher, &predicate.literal)?;
    }

    cypher.push_str(" RETURN ");
    if read.distinct {
        cypher.push_str("DISTINCT ");
    }
    let mut aliases = HashSet::new();
    for (index, projection) in read.projections.iter().enumerate() {
        let location = Some(projection.alias_span.location);
        let column = if projection.alias.is_empty() && projection.property.name.is_empty() {
            projection.property.variable.clone()
        } else if projection.alias.is_empty() {
            format!(
                "{}.{}",
                projection.property.variable, projection.property.name
            )
        } else {
            projection.alias.clone()
        };
        if !aliases.insert(column.to_ascii_lowercase()) {
            return Err(input_error(
                "QW_GQL_SUBSET: Duplicate projection alias",
                location,
            ));
        }
        if index > 0 {
            cypher.push_str(", ");
        }
        property(&mut cypher, read, &projection.property)?;
        if !projection.alias.is_empty() {
            cypher.push_str(" AS ");
            identifier(&mut cypher, &projection.alias, location)?;
        }
    }
    for (index, (name, descending)) in read.order.iter().enumerate() {
        if !read
            .projections
            .iter()
            .any(|projection| projection.alias == *name)
        {
            return Err(input_error(
                "QW_GQL_SUBSET: Expected projected order key",
                None,
            ));
        }
        cypher.push_str(if index == 0 { " ORDER BY " } else { ", " });
        identifier(&mut cypher, name, None)?;
        cypher.push_str(if *descending { " DESC" } else { " ASC" });
    }
    if let Some(limit) = read.limit {
        write!(cypher, " LIMIT {limit}").unwrap();
    }
    Ok(cypher)
}

fn node(cypher: &mut String, node: &NodePattern) -> Result<()> {
    cypher.push('(');
    identifier(cypher, &node.variable, Some(node.variable_span.location))?;
    cypher.push(':');
    identifier(cypher, &node.label, None)?;
    cypher.push(')');
    Ok(())
}

fn property(cypher: &mut String, read: &ParsedRead, property: &Property) -> Result<()> {
    let location = Some(property.variable_span.location);
    if property.variable != read.left.variable
        && !read
            .right
            .as_ref()
            .is_some_and(|right| property.variable == right.variable)
        && Some(&property.variable) != read.relationship_variable.as_ref()
        && !(property.name.is_empty() && Some(&property.variable) == read.path_variable.as_ref())
    {
        return Err(input_error(
            "QW_GQL_SUBSET: Property must use a matched variable",
            location,
        ));
    }
    identifier(cypher, &property.variable, location)?;
    if property.name.is_empty() {
        return Ok(());
    }
    cypher.push('.');
    identifier(cypher, &property.name, None)
}

fn identifier(cypher: &mut String, value: &str, location: Option<Location>) -> Result<()> {
    if !is_identifier(value) {
        return Err(input_error(
            "QW_GQL_SUBSET: Expected an ASCII identifier",
            location,
        ));
    }
    cypher.push('`');
    cypher.push_str(value);
    cypher.push('`');
    Ok(())
}

fn literal(cypher: &mut String, literal: &Literal) -> Result<()> {
    match literal {
        Literal::Parameter(name) => {
            if !is_identifier(name) {
                return Err(input_error(
                    "QW_GQL_SUBSET: Unsupported graph parameter name",
                    None,
                ));
            }
            cypher.push('$');
            cypher.push_str(name);
        }
        Literal::Boolean(value) => cypher.push_str(if *value { "true" } else { "false" }),
        Literal::Integer(value) => write!(cypher, "{value}").unwrap(),
        Literal::String(value) => {
            cypher.push('\'');
            for character in value.chars() {
                match character {
                    '\0' => return Err(input_error("QW_GQL_SUBSET: Invalid string literal", None)),
                    '\\' => cypher.push_str("\\\\"),
                    '\'' => cypher.push_str("\\'"),
                    value if value.is_control() => {
                        write!(cypher, "\\u{:04x}", u32::from(value)).unwrap()
                    }
                    value => cypher.push(value),
                }
            }
            cypher.push('\'');
        }
    }
    Ok(())
}
