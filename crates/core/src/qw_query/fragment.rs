//! Structured SQL/PGQ provenance. Identifiers are restricted to the same ASCII
//! alphabet as the grammar, so the versioned descriptor needs no quoting rules.
use std::collections::HashMap;

use super::{BackendError, ColumnSpec, GraphCatalog, GraphPopulations, ScalarType, is_identifier};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum EntityKind {
    Node,
    Edge,
}

struct GraphEntity {
    variable: String,
    label: String,
    kind: EntityKind,
    unambiguous: bool,
}

struct GraphProperty {
    entity: usize,
    field: String,
}

pub(super) struct GraphFragment {
    pattern: String,
    projection: String,
    entities: Vec<GraphEntity>,
    slots: Vec<GraphProperty>,
}

impl GraphFragment {
    /// Decode the fixed forward path and ordered property slots. Reconstruct
    /// both clauses and compare the entire query before trusting any slot.
    /// The ordinary provider binder then determines the columns and types.
    pub(super) fn bind(wire: &str, query: &str) -> Option<Self> {
        let (path, fields) = wire.strip_prefix("v1|")?.split_once('|')?;
        let mut pattern = String::from("MATCH ");
        let mut bindings = HashMap::new();
        let mut entities = Vec::<GraphEntity>::new();
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
            let first = *bindings.entry(variable).or_insert(index);
            if first != index {
                entities[first].unambiguous = false;
            }
            entities.push(GraphEntity {
                variable: variable.to_owned(),
                label: label.to_owned(),
                kind,
                unambiguous: first == index,
            });
        }
        if entities.len() % 2 != 1 {
            return None;
        }

        let mut slots = Vec::new();
        let mut expressions = Vec::new();
        if !fields.is_empty() {
            for (index, reference) in fields.split(',').enumerate() {
                let (variable, field) = reference.split_once('.')?;
                let &entity = bindings.get(variable)?;
                if !is_identifier(field) {
                    return None;
                }
                slots.push(GraphProperty {
                    entity,
                    field: field.to_owned(),
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
            entities,
            slots,
        })
    }

    /// Infer a remote scalar projection from this verified fragment and its catalog.
    pub(super) fn declared_projection(
        &self,
        catalog: &GraphCatalog,
    ) -> Result<Vec<ColumnSpec>, BackendError> {
        if self.slots.is_empty() {
            return Ok(vec![ColumnSpec {
                name: "qw_row".to_owned(),
                data_type: ScalarType::BigInt,
            }]);
        }
        self.slots
            .iter()
            .enumerate()
            .map(|(index, slot)| {
                let entity = &self.entities[slot.entity];
                if !entity.unambiguous {
                    return Err(BackendError::Schema);
                }
                let kind = match entity.kind {
                    EntityKind::Node => "node",
                    EntityKind::Edge => "relationship",
                };
                let fields = catalog
                    .get(&format!("{kind}:{}", entity.label))
                    .ok_or(BackendError::Schema)?;
                let (_, field_type) = fields
                    .iter()
                    .find(|(name, _)| name == &slot.field)
                    .ok_or(BackendError::Schema)?;
                let data_type = match field_type.as_str() {
                    "BOOL" => ScalarType::Boolean,
                    "INT64" => ScalarType::BigInt,
                    "DOUBLE" => ScalarType::Double,
                    "STRING" => ScalarType::Varchar,
                    _ => return Err(BackendError::Schema),
                };
                Ok(ColumnSpec {
                    name: format!("qw_col{index}"),
                    data_type,
                })
            })
            .collect()
    }

    pub(super) fn pattern(&self) -> &str {
        &self.pattern
    }

    pub(super) fn projection(&self) -> &str {
        &self.projection
    }

    pub(super) fn steps(&self) -> usize {
        self.entities.len() / 2
    }

    pub(super) fn estimate(&self, populations: &GraphPopulations) -> Option<u64> {
        let driver = match self.entities.as_slice() {
            [node] => node,
            [_, edge, _] => edge,
            _ => return None,
        };
        match populations {
            // Ladybug's catalog has a single ASCII case-insensitive table namespace.
            GraphPopulations::ByTable(tables) => {
                tables.get(&driver.label.to_ascii_lowercase()).copied()
            }
            GraphPopulations::ByEntity { nodes, edges } => Some(match driver.kind {
                EntityKind::Node => *nodes,
                EntityKind::Edge => *edges,
            }),
        }
    }

    pub(super) fn property(&self, index: usize) -> Option<(&str, &str)> {
        let slot = self.slots.get(index)?;
        let entity = &self.entities[slot.entity];
        entity
            .unambiguous
            .then_some((&entity.variable, &slot.field))
    }

    pub(super) fn expr(&self, index: usize) -> Option<String> {
        if self.slots.is_empty() && index == 0 {
            return Some("1".to_owned());
        }
        self.slots
            .get(index)
            .map(|slot| format!("{}.{}", self.entities[slot.entity].variable, slot.field))
    }
}
