use std::ffi::{CStr, c_char, c_void};

use duckdb_neo::{
    AsRaw, DuckDBType, FromValue, Result, ToValue,
    connection::{Context, HasFactory, SettingScope},
    custom_option::{CustomOptionBuilder, CustomOptionCallbacks},
    error::Error,
    extension::Extension,
    value::Value,
};

unsafe extern "C" {
    fn qw_register_graph_grammar(factory: *mut c_void) -> *const c_char;
}

enum GraphOption {
    Graph,
    Dialect,
}

impl CustomOptionCallbacks for GraphOption {
    fn update(
        &self,
        context: &Context,
        value: Value,
        scope: SettingScope,
        reset: bool,
    ) -> Result<Value> {
        if matches!(scope, SettingScope::Global) {
            return Err(Error::invalid_input(
                "QW_CONFIG: Graph selection and dialect are session settings",
            ));
        }
        if reset {
            return match self {
                Self::Graph => "".value(context),
                Self::Dialect => "gql".value(context),
            };
        }
        let text = String::from_value(&value)?
            .ok_or_else(|| Error::invalid_input("QW_ARGUMENT: Expected a name"))?;
        match self {
            Self::Graph => {
                rusty_quack_core::qw_query::validate_graph_alias(context, &text)?;
                Ok(value)
            }
            Self::Dialect => match text.to_ascii_lowercase().as_str() {
                "gql" => "gql".value(context),
                "cypher" => "cypher".value(context),
                _ => Err(Error::invalid_input("QW_ARGUMENT: Expected gql or cypher")),
            },
        }
    }
}

pub fn register(extension: &Extension) -> Result<()> {
    for (name, description, initial, option) in [
        (
            "qw_selected_graph",
            "Ladybug graph selected by SESSION SET GRAPH",
            "",
            GraphOption::Graph,
        ),
        (
            "qw_graph_dialect",
            "Language for standalone graph statements",
            "gql",
            GraphOption::Dialect,
        ),
    ] {
        CustomOptionBuilder::new(name, description, String::logical_type(extension)?, option)
            .default_value(initial.value(extension)?)
            .default_scope(SettingScope::Session)
            .register(extension)?;
    }
    // The session factory is borrowed for this call. DuckDB owns the installed grammar.
    let error = unsafe { qw_register_graph_grammar(extension.factory()?.get_raw().cast()) };
    if !error.is_null() {
        let message = unsafe { CStr::from_ptr(error) }.to_string_lossy();
        return Err(Error::invalid_input(format!(
            "Could not register graph grammar: {message}"
        )));
    }
    Ok(())
}
