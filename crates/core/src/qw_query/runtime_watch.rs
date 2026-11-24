//! Recognize the grammar's direct-property scan before applying an execution-time key filter.
//! The internal table function can also be called from SQL, so validate its hints against
//! the actual pattern and projection before moving a predicate into Ladybug.
use super::is_identifier;

pub(super) const MAX_KEYS: usize = 64;

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
