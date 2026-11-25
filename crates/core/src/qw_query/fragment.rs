//! Structured SQL/PGQ provenance. Identifiers are restricted to the same ASCII
//! alphabet as the grammar, so the versioned descriptor needs no quoting rules.
use std::collections::HashMap;

use super::is_identifier;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum EntityKind {
    Node,
    Edge,
}

pub(super) struct GraphProperty {
    pub(super) variable: String,
    pub(super) field: String,
    pub(super) label: String,
    pub(super) kind: EntityKind,
    unambiguous: bool,
}

pub(super) struct GraphFragment {
    pattern: String,
    projection: String,
    slots: Vec<GraphProperty>,
    steps: usize,
}

impl GraphFragment {
    /// Decode the fixed forward path and ordered property slots. Reconstruct
    /// both clauses and compare the entire query before trusting any slot.
    /// The ordinary provider binder then determines the columns and types.
    pub(super) fn bind(wire: &str, query: &str) -> Option<Self> {
        let (path, fields) = wire.strip_prefix("v1|")?.split_once('|')?;
        let mut pattern = String::from("MATCH ");
        let mut bindings = HashMap::new();
        let mut element_count = 0;
        for (index, token) in path.split(',').enumerate() {
            let (tag, names) = token.split_once(':')?;
            let (variable, label) = names.split_once(':')?;
            if !is_identifier(variable) || !is_identifier(label) {
                return None;
            }
            let kind = match (index % 2, tag) {
                (0, "n") => {
                    pattern.push_str(&format!("({variable}:{label})"));
                    EntityKind::Node
                }
                (1, "e") => {
                    pattern.push_str(&format!("-[{variable}:{label}]->"));
                    EntityKind::Edge
                }
                _ => return None,
            };
            bindings
                .entry(variable)
                .and_modify(|(_, _, unique)| *unique = false)
                .or_insert((kind, label, true));
            element_count = index + 1;
        }
        if element_count % 2 != 1 {
            return None;
        }

        let mut slots = Vec::new();
        let mut expressions = Vec::new();
        if !fields.is_empty() {
            for (index, reference) in fields.split(',').enumerate() {
                let (variable, field) = reference.split_once('.')?;
                let &(kind, label, unambiguous) = bindings.get(variable)?;
                if !is_identifier(field) {
                    return None;
                }
                slots.push(GraphProperty {
                    variable: variable.to_owned(),
                    field: field.to_owned(),
                    label: label.to_owned(),
                    kind,
                    unambiguous,
                });
                expressions.push(format!("{reference} AS qw_col{index}"));
            }
        }
        let projection = if expressions.is_empty() {
            String::from("1 AS qw_row")
        } else {
            expressions.join(", ")
        };
        if query != format!("{pattern} RETURN {projection}") {
            return None;
        }
        Some(Self {
            pattern,
            projection,
            slots,
            steps: element_count / 2,
        })
    }

    pub(super) fn pattern(&self) -> &str {
        &self.pattern
    }

    pub(super) fn projection(&self) -> &str {
        &self.projection
    }

    pub(super) fn steps(&self) -> usize {
        self.steps
    }

    pub(super) fn property(&self, index: usize) -> Option<&GraphProperty> {
        self.slots.get(index).filter(|slot| slot.unambiguous)
    }

    pub(super) fn expr(&self, index: usize) -> Option<String> {
        if self.slots.is_empty() && index == 0 {
            return Some("1".to_owned());
        }
        self.slots
            .get(index)
            .map(|slot| format!("{}.{}", slot.variable, slot.field))
    }
}
