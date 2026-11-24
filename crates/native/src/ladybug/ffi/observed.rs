use std::{
    cell::Cell,
    ffi::{CStr, c_char, c_int},
};

use crate::test_observation::{Fault, event, fault};

use super::{
    ArrowArray, ConnectionHandle, DatabaseHandle, PreparedHandle, QueryResultHandle, SUCCESS,
};

const ERROR: c_int = 1;
static TIMEOUT_MESSAGE: &CStr = c"Interrupted.";

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub(in crate::ladybug) struct NativeCalls {
    pub prepare: usize,
    pub read_only_check: usize,
    pub execute: usize,
    pub arrow_pull: usize,
}

thread_local! {
    static NATIVE_CALLS: Cell<NativeCalls> = const {
        Cell::new(NativeCalls { prepare: 0, read_only_check: 0, execute: 0, arrow_pull: 0 })
    };
}

pub(in crate::ladybug) fn native_calls() -> NativeCalls {
    NATIVE_CALLS.get()
}

pub(in crate::ladybug) fn reset_native_calls() {
    NATIVE_CALLS.set(NativeCalls::default());
}

fn record(call: impl FnOnce(&mut NativeCalls)) {
    NATIVE_CALLS.with(|slot| {
        let mut calls = slot.get();
        call(&mut calls);
        slot.set(calls);
    });
}

// Test builds count calls at the real C ABI boundary. These wrappers always forward to the
// same linked implementation, so the tests exercise the native parser, planner and results.
unsafe extern "C" {
    #[link_name = "qw_ladybug_open_database"]
    fn native_open(path: *const c_char, read_only: bool, database: *mut DatabaseHandle) -> c_int;

    #[link_name = "qw_ladybug_is_graph_read"]
    fn native_ast_read(text: *const c_char) -> bool;

    #[link_name = "lbug_connection_destroy"]
    fn native_connection_destroy(connection: *mut ConnectionHandle);

    #[link_name = "lbug_connection_prepare"]
    fn native_prepare(
        connection: *mut ConnectionHandle,
        query: *const c_char,
        prepared: *mut PreparedHandle,
    ) -> c_int;

    #[link_name = "lbug_prepared_statement_is_success"]
    fn native_prepare_success(prepared: *mut PreparedHandle) -> bool;

    #[link_name = "lbug_prepared_statement_is_read_only"]
    fn native_is_read_only(prepared: *mut PreparedHandle) -> bool;

    #[link_name = "lbug_connection_execute"]
    fn native_execute(
        connection: *mut ConnectionHandle,
        prepared: *mut PreparedHandle,
        result: *mut QueryResultHandle,
    ) -> c_int;

    #[link_name = "lbug_query_result_get_next_arrow_chunk"]
    fn native_arrow_pull(
        result: *mut QueryResultHandle,
        chunk_size: i64,
        array: *mut ArrowArray,
    ) -> c_int;

    #[link_name = "lbug_get_last_error"]
    fn native_last_error() -> *mut c_char;

    #[link_name = "lbug_destroy_string"]
    fn native_destroy_string(message: *mut c_char);
}

fn outcome(success: bool) -> &'static str {
    if success { "ok" } else { "error" }
}

pub(in crate::ladybug) unsafe fn qw_ladybug_open_database(
    path: *const c_char,
    read_only: bool,
    database: *mut DatabaseHandle,
) -> c_int {
    let status = unsafe { native_open(path, read_only, database) };
    event(
        "open",
        outcome(status == SUCCESS),
        if read_only { "read_only" } else { "read_write" },
    );
    status
}

pub(in crate::ladybug) unsafe fn qw_ladybug_is_graph_read(text: *const c_char) -> bool {
    let admitted = unsafe { native_ast_read(text) };
    event(
        if admitted {
            "ast_admitted"
        } else {
            "ast_rejected"
        },
        outcome(admitted),
        "",
    );
    admitted
}

pub(in crate::ladybug) unsafe fn lbug_connection_destroy(connection: *mut ConnectionHandle) {
    let was_open = unsafe { connection.as_ref() }.is_some_and(|handle| !handle.ptr.is_null());
    unsafe { native_connection_destroy(connection) };
    if was_open {
        event("release", "ok", "");
    }
}

pub(in crate::ladybug) unsafe fn lbug_connection_prepare(
    connection: *mut ConnectionHandle,
    query: *const c_char,
    prepared: *mut PreparedHandle,
) -> c_int {
    record(|calls| calls.prepare += 1);
    let status = unsafe { native_prepare(connection, query, prepared) };
    event("prepare", outcome(status == SUCCESS), "");
    status
}

pub(in crate::ladybug) unsafe fn lbug_prepared_statement_is_success(
    prepared: *mut PreparedHandle,
) -> bool {
    let success = unsafe { native_prepare_success(prepared) };
    event("prepare_success", outcome(success), "");
    success
}

pub(in crate::ladybug) unsafe fn lbug_prepared_statement_is_read_only(
    prepared: *mut PreparedHandle,
) -> bool {
    record(|calls| calls.read_only_check += 1);
    let read_only = unsafe { native_is_read_only(prepared) };
    event("prepared_read_only", outcome(read_only), "");
    read_only
}

pub(in crate::ladybug) unsafe fn lbug_connection_execute(
    connection: *mut ConnectionHandle,
    prepared: *mut PreparedHandle,
    result: *mut QueryResultHandle,
) -> c_int {
    record(|calls| calls.execute += 1);
    let status = unsafe { native_execute(connection, prepared, result) };
    event("execute", outcome(status == SUCCESS), "");
    if status == SUCCESS {
        let injected = match fault() {
            Some(Fault::Timeout) => "timeout",
            Some(Fault::Execution) => "execution",
            _ => return status,
        };
        event("fault", "injected", injected);
        return ERROR;
    }
    status
}

pub(in crate::ladybug) unsafe fn lbug_query_result_get_next_arrow_chunk(
    result: *mut QueryResultHandle,
    chunk_size: i64,
    array: *mut ArrowArray,
) -> c_int {
    record(|calls| calls.arrow_pull += 1);
    let status = unsafe { native_arrow_pull(result, chunk_size, array) };
    let rows = if status == SUCCESS {
        unsafe { (*array).length }.to_string()
    } else {
        String::new()
    };
    event("arrow_pull", outcome(status == SUCCESS), &rows);
    if status == SUCCESS
        && fault() == Some(Fault::ArrowAfterBatch)
        && native_calls().arrow_pull == 2
    {
        unsafe { (*array).n_buffers = 0 };
        event("fault", "injected", "arrow");
    }
    status
}

pub(in crate::ladybug) unsafe fn lbug_get_last_error() -> *mut c_char {
    if fault() == Some(Fault::Timeout) {
        return TIMEOUT_MESSAGE.as_ptr().cast_mut();
    }
    unsafe { native_last_error() }
}

pub(in crate::ladybug) unsafe fn lbug_destroy_string(message: *mut c_char) {
    if message != TIMEOUT_MESSAGE.as_ptr().cast_mut() {
        unsafe { native_destroy_string(message) };
    }
}
