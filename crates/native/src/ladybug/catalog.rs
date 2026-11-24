//! The graph registration owns its metadata. Binding an empty or nonempty result
//! uses the same Ladybug parse tree and never opens the graph's execution path.
use std::ffi::{CStr, CString, c_char, c_void};
use std::path::Path;

use rusty_quack_core::qw_query::{BackendError, ColumnSpec, GraphCatalog, ScalarType};

use super::{ColumnData, Connection, Database, QueryResult, arrow, ffi};

type Visit = unsafe extern "C" fn(*mut c_void, *const c_char, *const c_char, *const c_char) -> bool;

unsafe extern "C" {
    fn qw_ladybug_project(query: *const c_char, visit: Visit, output: *mut c_void) -> bool;
}

pub(super) fn snapshot(path: &Path) -> Option<GraphCatalog> {
    let mut db = Database::open(path, true).ok()?;
    let mut connection = Connection::open(&mut db).ok()?;
    // A single read transaction covers table enumeration and per-label property metadata.
    // Dropping the private connection rolls it back, including on any error.
    catalog_query(&mut connection, "BEGIN TRANSACTION READ ONLY")?;
    let mut catalog = GraphCatalog::new();
    for names in catalog_rows(&mut connection, "CALL show_tables() RETURN name AS label")? {
        let label = names.first()?;
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
    Some(catalog)
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
    let ty = if label.is_empty() {
        // A typed scalar literal carries its own type in the expression tree.
        Some(prop)
    } else {
        result
            .catalog
            .iter()
            .find(|(name, _)| name.eq_ignore_ascii_case(label))
            .and_then(|(_, fields)| {
                fields
                    .iter()
                    .find(|(name, _)| name.eq_ignore_ascii_case(prop))
            })
            .map(|(_, ty)| ty.as_str())
    };
    let data_type = match ty {
        Some("INT64") => ScalarType::BigInt,
        Some("STRING") => ScalarType::Varchar,
        Some("BOOL") => ScalarType::Boolean,
        Some("DOUBLE") => ScalarType::Double,
        _ => return false,
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
