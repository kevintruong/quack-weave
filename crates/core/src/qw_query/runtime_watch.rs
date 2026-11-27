//! Recognize the grammar's direct-property scan before applying an execution-time key filter.
//! The internal table function can also be called from SQL, so validate its hints against
//! the actual pattern and projection before moving a predicate into the provider.
use duckdb_neo::{
    DuckDBType, FromValue, Result, ToValue,
    connection::{Context, SettingScope},
    custom_option::{CustomOptionBuilder, CustomOptionCallbacks},
    error::Error,
    extension::Extension,
    log::{Log, LogLevel},
    value::Value,
};

use super::{BoundRead, ScalarType, is_identifier};

pub(super) const MAX_KEYS: usize = 64;
const ENABLE_WATCHLIST: &str = "qw_enable_runtime_watchlist";

#[derive(Clone, Copy)]
pub(super) enum WatchlistRoute {
    Host,
    LiteralExact,
    RuntimeExact,
}

impl WatchlistRoute {
    pub(super) fn log(self, context: &Context) {
        let route = match self {
            Self::Host => "host",
            Self::LiteralExact => "literal_exact",
            Self::RuntimeExact => "runtime_exact",
        };
        // The route was dispatched. Logging must never affect read execution.
        let _ = Log::log_on_context(context, LogLevel::Info, route, "QuackWeaveGraphRoute");
    }
}

struct WatchlistOption;

impl CustomOptionCallbacks for WatchlistOption {
    fn update(
        &self,
        context: &Context,
        value: Value,
        scope: SettingScope,
        is_reset: bool,
    ) -> Result<Value> {
        if !matches!(scope, SettingScope::Session) {
            return Err(Error::invalid_input(
                "QW_CONFIG: Use SET SESSION for qw_enable_runtime_watchlist",
            ));
        }
        if is_reset {
            return true.value(context);
        }
        if bool::from_value(&value)?.is_none() {
            return Err(Error::invalid_input(
                "QW_CONFIG: Expected a boolean for qw_enable_runtime_watchlist",
            ));
        }
        Ok(value)
    }
}

pub(super) fn register(extension: &Extension) -> Result<()> {
    CustomOptionBuilder::new(
        ENABLE_WATCHLIST,
        "Apply exact literal or execution-local watchlist keys to QuackWeave graph reads",
        bool::logical_type(extension)?,
        WatchlistOption,
    )
    .default_value(true.value(extension)?)
    .default_scope(SettingScope::Session)
    .register(extension)
}

pub(super) fn enabled(context: &Context) -> Result<bool> {
    let (value, _) = context.config()?.get_value(ENABLE_WATCHLIST)?;
    Ok(bool::from_value(&value)? == Some(true))
}

impl BoundRead {
    /// DuckDB supplies optional filters only during initialization of this
    /// physical scan. Key values never become part of a reusable bound plan.
    pub(super) fn runtime_predicate(&self) -> Option<String> {
        let fragment = self.fragment.as_ref()?;
        for (index, col) in self.schema.iter().enumerate() {
            if col.data_type != ScalarType::BigInt || fragment.property(index).is_none() {
                continue;
            }
            let keys = self.provider.backend.runtime_watch_keys(index);
            if keys.is_empty() || keys.len() > MAX_KEYS {
                continue;
            }
            let values = keys
                .iter()
                .map(i64::to_string)
                .collect::<Vec<_>>()
                .join(",");
            return Some(format!("{} IN [{values}]", fragment.expr(index)?));
        }
        None
    }
}

/// Locate the column constrained by the grammar's literal candidate. The filter
/// can only restrict the base MATCH and must preserve every projected expression.
pub(super) fn filtered_column(
    base: &str,
    candidate: &str,
    label: &str,
    property: &str,
) -> Option<usize> {
    let (pattern, projection) = base.split_once(" RETURN ")?;
    let (filtered, returned) = candidate.split_once(" RETURN ")?;
    if projection != returned {
        return None;
    }
    let predicate = filtered.strip_prefix(pattern)?.strip_prefix(" WHERE ")?;
    let (key, values) = predicate.split_once(' ')?;
    let (var, field) = key.split_once('.')?;
    if field != property {
        return None;
    }
    if let Some(literal) = values.strip_prefix("= ") {
        literal.parse::<i64>().ok()?;
    } else {
        let list = values.strip_prefix("IN [")?.strip_suffix(']')?;
        if list.split(',').count() > MAX_KEYS
            || !list.split(',').all(|v| v.trim().parse::<i64>().is_ok())
        {
            return None;
        }
    }
    let column = projection.split(", ").find_map(|item| {
        let (expr, alias) = item.split_once(" AS ")?;
        (expr == key).then_some(alias)
    })?;
    RuntimeWatch::from_scan(base, label, property, var, column).map(|watch| watch.column)
}

pub(super) struct RuntimeWatch {
    pub(super) column: usize,
    pattern: String,
    projection: String,
    property: String,
}

impl RuntimeWatch {
    pub(super) fn from_scan(
        query: &str,
        label: &str,
        property: &str,
        var: &str,
        column: &str,
    ) -> Option<Self> {
        let (pattern, projection) = query.strip_prefix("MATCH ")?.split_once(" RETURN ")?;
        let mut rest = pattern;
        let mut bindings = Vec::new();
        loop {
            rest = element(rest.strip_prefix('(')?, ')', &mut bindings)?;
            if rest.is_empty() {
                break;
            }
            rest = element(rest.strip_prefix("-[")?, ']', &mut bindings)?.strip_prefix("->")?;
        }
        let mut var_labels = bindings
            .iter()
            .filter_map(|(v, l)| (*v == var).then_some(*l));
        if var_labels.next()? != label || var_labels.next().is_some() {
            return None;
        }
        let column = column.strip_prefix("qw_col")?.parse::<usize>().ok()?;
        let key = format!("{var}.{property}");
        let mut key_matched = false;
        for (i, output) in projection.split(", ").enumerate() {
            let (expr, alias) = output.split_once(" AS ")?;
            let (v, p) = expr.split_once('.')?;
            if alias != format!("qw_col{i}")
                || !is_identifier(p)
                || !bindings.iter().any(|(b, _)| v == *b)
            {
                return None;
            }
            key_matched |= i == column && expr == key;
        }
        key_matched.then(|| Self {
            column,
            pattern: pattern.into(),
            projection: projection.into(),
            property: key,
        })
    }

    pub(super) fn query(&self, keys: &[i64]) -> Option<String> {
        if keys.is_empty() || keys.len() > MAX_KEYS {
            return None;
        }
        let ints = keys
            .iter()
            .map(i64::to_string)
            .collect::<Vec<_>>()
            .join(",");
        Some(format!(
            "MATCH {} WHERE {} IN [{}] RETURN {}",
            self.pattern, self.property, ints, self.projection
        ))
    }
}

fn element<'a>(
    rest: &'a str,
    close: char,
    bindings: &mut Vec<(&'a str, &'a str)>,
) -> Option<&'a str> {
    let (node, rest) = rest.split_once(close)?;
    let (var, label) = node.split_once(':')?;
    if !is_identifier(var) || !is_identifier(label) {
        return None;
    }
    bindings.push((var, label));
    Some(rest)
}
