//! The graph registration owns its metadata. Binding an empty or nonempty result
//! uses the same Ladybug parse tree and never opens the graph's execution path.
use std::collections::BTreeMap;
use std::ffi::{CStr, CString, c_char, c_void};
use std::path::Path;

use rusty_quack_core::qw_query::{BackendError, ColumnSpec, GraphCatalog, ScalarType};

use super::{ColumnData, Connection, Database, QueryResult, arrow, ffi};

// Discriminants shared with qw_ladybug_project. Each path emits its component labels
// in traversal order, followed by PATH to finish the two typed lists.
const PROPERTY: u8 = 0;
const NODE: u8 = 1;
const RELATIONSHIP: u8 = 2;
const PATH: u8 = 3;
const PATH_NODE: u8 = 4;
const PATH_EDGE: u8 = 5;

type Visit =
    unsafe extern "C" fn(*mut c_void, u8, *const c_char, *const c_char, *const c_char) -> bool;

unsafe extern "C" {
    fn qw_ladybug_table_population(
        connection: *const ffi::ConnectionHandle,
        label: *const c_char,
        rows: *mut u64,
    ) -> bool;
    fn qw_ladybug_project(query: *const c_char, visit: Visit, output: *mut c_void) -> bool;
}

pub(super) fn snapshot(path: &Path) -> Option<(GraphCatalog, BTreeMap<String, u64>)> {
    let mut db = Database::open(path, true).ok()?;
    let mut connection = Connection::open(&mut db).ok()?;
    // A single read transaction covers table enumeration and per-label property metadata.
    // Dropping the private connection rolls it back, including on any error.
    catalog_query(&mut connection, "BEGIN TRANSACTION READ ONLY")?;
    let mut catalog = GraphCatalog::new();
    let mut populations = BTreeMap::new();
    for names in catalog_rows(&mut connection, "CALL show_tables() RETURN name AS label")? {
        let label = names.first()?;
        let name = CString::new(label.as_str()).ok()?;
        let mut count = 0;
        if unsafe { qw_ladybug_table_population(&connection.0, name.as_ptr(), &mut count) } {
            populations.insert(label.to_ascii_lowercase(), count);
        }
        let quoted = label.replace('\\', "\\\\").replace('\'', "\\\'");
        let query = format!(
            "CALL table_info('{quoted}') RETURN name AS property_name, type AS property_type ORDER BY `property id`"
        );
        let properties = catalog.entry(label.clone()).or_default();
        for property in catalog_rows(&mut connection, &query)? {
            let [name, ty] = property.as_slice() else {
                return None;
            };
            properties.push((name.clone(), ty.clone()));
        }
    }
    Some((catalog, populations))
}

fn catalog_query(connection: &mut Connection, query: &str) -> Option<QueryResult> {
    let query = CString::new(query).ok()?;
    let mut result = QueryResult::default();
    let status =
        unsafe { ffi::lbug_connection_query(&mut connection.0, query.as_ptr(), &mut result.0) };
    (status == ffi::SUCCESS).then_some(result)
}

fn catalog_rows(connection: &mut Connection, query: &str) -> Option<Vec<Vec<String>>> {
    let mut result = catalog_query(connection, query)?;
    let rows = unsafe { ffi::lbug_query_result_get_num_tuples(&mut result.0) };
    if rows == 0 {
        return Some(Vec::new());
    }
    let mut schema = ffi::ArrowSchema::default();
    if unsafe { ffi::lbug_query_result_get_arrow_schema(&mut result.0, &mut schema) }
        != ffi::SUCCESS
    {
        return None;
    }
    let (_, types) = arrow::read_schema(&schema).ok()?;
    let mut strings = Vec::new();
    while strings.len() < usize::try_from(rows).ok()? {
        let mut array = ffi::ArrowArray::default();
        if unsafe {
            ffi::lbug_query_result_get_next_arrow_chunk(
                &mut result.0,
                i64::try_from(rows).ok()?,
                &mut array,
            )
        } != ffi::SUCCESS
        {
            return None;
        }
        let batch = arrow::read_batch(&array, &types, None).ok()?;
        if batch.len == 0 {
            return None;
        }
        let mut slice = vec![Vec::with_capacity(batch.columns.len()); batch.len];
        for column in batch.columns {
            let ColumnData::Varchar(values) = column else {
                return None;
            };
            for (row, value) in slice.iter_mut().zip(values) {
                row.push(value?);
            }
        }
        strings.extend(slice);
    }
    Some(strings)
}

struct Projection<'a> {
    catalog: &'a GraphCatalog,
    nodes: Vec<ColumnSpec>,
    edges: Vec<ColumnSpec>,
    columns: Vec<ColumnSpec>,
}

pub(super) fn projection(
    catalog: &GraphCatalog,
    query: &str,
) -> Result<Vec<ColumnSpec>, BackendError> {
    let query = CString::new(query).map_err(|_| BackendError::Admission)?;
    if !unsafe { super::ffi::qw_ladybug_is_graph_read(query.as_ptr()) } {
        return Err(BackendError::Admission);
    }
    let mut result = Projection {
        catalog,
        columns: Vec::new(),
        nodes: Vec::new(),
        edges: Vec::new(),
    };
    let ok = unsafe {
        qw_ladybug_project(
            query.as_ptr(),
            project,
            (&mut result as *mut Projection<'_>).cast(),
        )
    };
    ok.then_some(result.columns).ok_or(BackendError::Schema)
}

unsafe extern "C" fn project(
    output: *mut c_void,
    kind: u8,
    label: *const c_char,
    prop: *const c_char,
    name: *const c_char,
) -> bool {
    let result = unsafe { &mut *output.cast::<Projection<'_>>() };
    let (Ok(label), Ok(prop), Ok(name)) = (
        unsafe { CStr::from_ptr(label) }.to_str(),
        unsafe { CStr::from_ptr(prop) }.to_str(),
        unsafe { CStr::from_ptr(name) }.to_str(),
    ) else {
        return false;
    };
    let data_type = match kind {
        PROPERTY if label.is_empty() => scalar_type(prop),
        PROPERTY => schema_fields(result.catalog, label).and_then(|fields| {
            fields
                .iter()
                .find(|(name, _)| name.eq_ignore_ascii_case(prop))
                .and_then(|(_, ty)| scalar_type(ty))
        }),
        NODE => entity(result.catalog, label, false),
        RELATIONSHIP => entity(result.catalog, label, true),
        PATH if !result.nodes.is_empty() && !result.edges.is_empty() => {
            let nodes = ScalarType::Struct(std::mem::take(&mut result.nodes));
            let edges = ScalarType::Struct(std::mem::take(&mut result.edges));
            Some(ScalarType::Struct(vec![
                field("_NODES", ScalarType::List(Box::new(nodes))),
                field("_RELS", ScalarType::List(Box::new(edges))),
            ]))
        }
        PATH_NODE | PATH_EDGE => {
            let Some(ScalarType::Struct(fields)) = entity(result.catalog, label, kind == PATH_EDGE)
            else {
                return false;
            };
            let merged = if kind == PATH_EDGE {
                &mut result.edges
            } else {
                &mut result.nodes
            };
            for field in fields {
                if let Some(previous) = merged.iter().find(|previous| previous.name == field.name) {
                    if previous.data_type != field.data_type {
                        return false;
                    }
                } else {
                    merged.push(field);
                }
            }
            return true;
        }
        _ => None,
    };
    let Some(data_type) = data_type else {
        return false;
    };
    if result
        .columns
        .iter()
        .any(|c| c.name.eq_ignore_ascii_case(name))
    {
        return false;
    }
    result.columns.push(ColumnSpec {
        name: name.into(),
        data_type,
    });
    true
}

fn field(name: &str, data_type: ScalarType) -> ColumnSpec {
    ColumnSpec {
        name: name.to_owned(),
        data_type,
    }
}

fn scalar_type(ty: &str) -> Option<ScalarType> {
    Some(match ty {
        "INT64" => ScalarType::BigInt,
        "STRING" => ScalarType::Varchar,
        "BOOL" => ScalarType::Boolean,
        "DOUBLE" => ScalarType::Double,
        _ => return None,
    })
}

fn schema_fields<'c>(catalog: &'c GraphCatalog, label: &str) -> Option<&'c Vec<(String, String)>> {
    catalog
        .iter()
        .find(|(name, _)| name.eq_ignore_ascii_case(label))
        .map(|(_, fields)| fields)
}

fn entity(catalog: &GraphCatalog, label: &str, relationship: bool) -> Option<ScalarType> {
    let properties = schema_fields(catalog, label)?;
    let id = || {
        ScalarType::Struct(vec![
            field("offset", ScalarType::BigInt),
            field("table", ScalarType::BigInt),
        ])
    };
    let mut fields = if relationship {
        vec![
            field("_SRC", id()),
            field("_DST", id()),
            field("_LABEL", ScalarType::Varchar),
            field("_ID", id()),
        ]
    } else {
        vec![field("_ID", id()), field("_LABEL", ScalarType::Varchar)]
    };
    for (name, ty) in properties {
        fields.push(field(name, scalar_type(ty)?));
    }
    Some(ScalarType::Struct(fields))
}
