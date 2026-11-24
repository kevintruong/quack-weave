use std::{
    cell::Cell,
    ffi::{c_char, c_int},
};

use super::{ArrowArray, ConnectionHandle, PreparedHandle, QueryResultHandle};

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
    #[link_name = "lbug_connection_prepare"]
    fn native_prepare(
        connection: *mut ConnectionHandle,
        query: *const c_char,
        prepared: *mut PreparedHandle,
    ) -> c_int;

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
}

pub(in crate::ladybug) unsafe fn lbug_connection_prepare(
    connection: *mut ConnectionHandle,
    query: *const c_char,
    prepared: *mut PreparedHandle,
) -> c_int {
    record(|calls| calls.prepare += 1);
    unsafe { native_prepare(connection, query, prepared) }
}

pub(in crate::ladybug) unsafe fn lbug_prepared_statement_is_read_only(
    prepared: *mut PreparedHandle,
) -> bool {
    record(|calls| calls.read_only_check += 1);
    unsafe { native_is_read_only(prepared) }
}

pub(in crate::ladybug) unsafe fn lbug_connection_execute(
    connection: *mut ConnectionHandle,
    prepared: *mut PreparedHandle,
    result: *mut QueryResultHandle,
) -> c_int {
    record(|calls| calls.execute += 1);
    unsafe { native_execute(connection, prepared, result) }
}

pub(in crate::ladybug) unsafe fn lbug_query_result_get_next_arrow_chunk(
    result: *mut QueryResultHandle,
    chunk_size: i64,
    array: *mut ArrowArray,
) -> c_int {
    record(|calls| calls.arrow_pull += 1);
    unsafe { native_arrow_pull(result, chunk_size, array) }
}
