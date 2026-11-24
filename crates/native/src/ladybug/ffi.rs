use std::ffi::{c_char, c_int, c_void};

pub(super) const SUCCESS: c_int = 0;

#[repr(C)]
#[derive(Default)]
pub(super) struct DatabaseHandle {
    pub ptr: *mut c_void,
}

#[repr(C)]
#[derive(Default)]
pub(super) struct ConnectionHandle {
    pub ptr: *mut c_void,
}

#[repr(C)]
#[derive(Default)]
pub(super) struct PreparedHandle {
    ptr: *mut c_void,
    bound_values: *mut c_void,
}

#[repr(C)]
#[derive(Default)]
pub(super) struct QueryResultHandle {
    ptr: *mut c_void,
    owned_by_cpp: bool,
}

#[repr(C)]
#[derive(Default)]
pub(super) struct ArrowSchema {
    pub format: *const c_char,
    pub name: *const c_char,
    pub metadata: *const c_char,
    pub flags: i64,
    pub n_children: i64,
    pub children: *const *const ArrowSchema,
    pub dictionary: *const ArrowSchema,
    pub release: Option<unsafe extern "C" fn(*mut ArrowSchema)>,
    pub private_data: *mut c_void,
}

impl Drop for ArrowSchema {
    fn drop(&mut self) {
        if let Some(release) = self.release {
            unsafe { release(self) };
        }
    }
}

#[repr(C)]
#[derive(Default)]
pub(super) struct ArrowArray {
    pub length: i64,
    pub null_count: i64,
    pub offset: i64,
    pub n_buffers: i64,
    pub n_children: i64,
    pub buffers: *const *const c_void,
    pub children: *const *const ArrowArray,
    pub dictionary: *const ArrowArray,
    pub release: Option<unsafe extern "C" fn(*mut ArrowArray)>,
    pub private_data: *mut c_void,
}

impl Drop for ArrowArray {
    fn drop(&mut self) {
        if let Some(release) = self.release {
            unsafe { release(self) };
        }
    }
}

unsafe extern "C" {
    pub(super) fn qw_ladybug_open_database(
        path: *const c_char,
        read_only: bool,
        database: *mut DatabaseHandle,
    ) -> c_int;
    pub(super) fn qw_ladybug_is_graph_read(text: *const c_char) -> bool;

    pub(super) fn lbug_database_destroy(database: *mut DatabaseHandle);
    pub(super) fn lbug_connection_init(
        database: *mut DatabaseHandle,
        connection: *mut ConnectionHandle,
    ) -> c_int;
    pub(super) fn lbug_connection_destroy(connection: *mut ConnectionHandle);
    pub(super) fn lbug_connection_set_query_timeout(
        connection: *mut ConnectionHandle,
        timeout_ms: u64,
    ) -> c_int;
    #[cfg(not(test))]
    pub(super) fn lbug_connection_prepare(
        connection: *mut ConnectionHandle,
        query: *const c_char,
        prepared: *mut PreparedHandle,
    ) -> c_int;
    pub(super) fn lbug_prepared_statement_is_success(prepared: *mut PreparedHandle) -> bool;
    #[cfg(not(test))]
    pub(super) fn lbug_prepared_statement_is_read_only(prepared: *mut PreparedHandle) -> bool;
    pub(super) fn lbug_prepared_statement_destroy(prepared: *mut PreparedHandle);
    #[cfg(not(test))]
    pub(super) fn lbug_connection_execute(
        connection: *mut ConnectionHandle,
        prepared: *mut PreparedHandle,
        result: *mut QueryResultHandle,
    ) -> c_int;
    pub(super) fn lbug_query_result_destroy(result: *mut QueryResultHandle);
    pub(super) fn lbug_query_result_get_num_tuples(result: *mut QueryResultHandle) -> u64;
    pub(super) fn lbug_query_result_get_arrow_schema(
        result: *mut QueryResultHandle,
        schema: *mut ArrowSchema,
    ) -> c_int;
    #[cfg(not(test))]
    pub(super) fn lbug_query_result_get_next_arrow_chunk(
        result: *mut QueryResultHandle,
        chunk_size: i64,
        array: *mut ArrowArray,
    ) -> c_int;
    pub(super) fn lbug_get_last_error() -> *mut c_char;
    pub(super) fn lbug_destroy_string(message: *mut c_char);

    #[cfg(test)]
    pub(super) fn lbug_connection_query(
        connection: *mut ConnectionHandle,
        query: *const c_char,
        result: *mut QueryResultHandle,
    ) -> c_int;
}

#[cfg(test)]
mod observed;

#[cfg(test)]
pub(super) use observed::{
    NativeCalls, lbug_connection_execute, lbug_connection_prepare,
    lbug_prepared_statement_is_read_only, lbug_query_result_get_next_arrow_chunk, native_calls,
    reset_native_calls,
};
