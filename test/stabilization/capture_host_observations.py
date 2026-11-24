#!/usr/bin/env python3
"""Observe chunks delivered by pinned DuckDB and a path swap after bind."""

import argparse
from contextlib import contextmanager
import ctypes as c
import hashlib
from pathlib import Path
import re
import shutil
import sys
import tempfile


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mvp1_acceptance import graph_query, provision, sql_literal
from run_sqllogictest import DUCKDB_PIN_SOURCE, DUCKDB_PIN_VERSION


class Result(c.Structure):
    # duckdb_result layout from the pinned DuckDB v2.0.1 C API.
    _fields_ = [
        ("column_count", c.c_uint64),
        ("row_count", c.c_uint64),
        ("rows_changed", c.c_uint64),
        ("columns", c.c_void_p),
        ("error_message", c.c_void_p),
        ("internal_data", c.c_void_p),
    ]


def duckdb_api(path):
    library = c.CDLL(str(path.resolve(strict=True)))
    pointer = c.c_void_p
    pointer_ref = c.POINTER(pointer)
    result_ref = c.POINTER(Result)
    string = c.c_char_p
    signatures = {
        "close": (None, pointer_ref),
        "connect": (c.c_int, pointer, pointer_ref),
        "create_config": (c.c_int, pointer_ref),
        "data_chunk_get_size": (c.c_uint64, pointer),
        "destroy_config": (None, pointer_ref),
        "destroy_data_chunk": (None, pointer_ref),
        "destroy_prepare": (None, pointer_ref),
        "destroy_result": (None, result_ref),
        "disconnect": (None, pointer_ref),
        "execute_prepared_streaming": (c.c_int, pointer, result_ref),
        "fetch_chunk": (pointer, Result),
        "free": (None, pointer),
        "library_version": (string,),
        "open_ext": (c.c_int, string, pointer_ref, pointer, pointer_ref),
        "prepare": (c.c_int, pointer, string, pointer_ref),
        "prepare_error": (string, pointer),
        "query": (c.c_int, pointer, string, result_ref),
        "result_error": (string, result_ref),
        "result_is_streaming": (c.c_bool, Result),
        "set_config": (c.c_int, pointer, string, string),
    }
    for name, (result, *arguments) in signatures.items():
        function = getattr(library, "duckdb_" + name)
        function.restype = result
        function.argtypes = arguments
    return library


def require_ok(status, operation, error=None):
    if status:
        detail = error.decode("utf-8", errors="replace") if error else "no diagnostic"
        raise RuntimeError(f"DuckDB {operation} failed: {detail}")


@contextmanager
def open_connection(api):
    config, database, connection, open_error = (c.c_void_p() for _ in range(4))
    try:
        require_ok(api.duckdb_create_config(c.byref(config)), "create config")
        require_ok(
            api.duckdb_set_config(config, b"allow_unsigned_extensions", b"true"), "allow local artifact"
        )
        status = api.duckdb_open_ext(None, c.byref(database), config, c.byref(open_error))
        require_ok(status, "open", c.string_at(open_error) if open_error else None)
        require_ok(api.duckdb_connect(database, c.byref(connection)), "connect")
        yield connection
    finally:
        if connection:
            api.duckdb_disconnect(c.byref(connection))
        if database:
            api.duckdb_close(c.byref(database))
        if open_error:
            api.duckdb_free(open_error)
        if config:
            api.duckdb_destroy_config(c.byref(config))


def execute_setup(api, connection, sql):
    result = Result()
    try:
        status = api.duckdb_query(connection, sql.encode(), c.byref(result))
        require_ok(status, "setup", api.duckdb_result_error(c.byref(result)))
    finally:
        api.duckdb_destroy_result(c.byref(result))


@contextmanager
def prepare(api, connection, sql, observe):
    statement = c.c_void_p()
    try:
        status = api.duckdb_prepare(connection, sql.encode(), c.byref(statement))
        if status:
            error = api.duckdb_prepare_error(statement) if statement else None
            observe("prepare", "error", diagnostic_code(error))
            require_ok(status, "prepare", error)
        observe("prepare", "ok")
        yield statement
    finally:
        if statement:
            api.duckdb_destroy_prepare(c.byref(statement))


def diagnostic_code(error):
    match = re.search(rb"\bQW_[A-Z_]+\b", error or b"")
    return match.group().decode("ascii") if match else "unclassified"


def count_delivered(api, statement, observe):
    result = Result()
    count = 0
    try:
        status = api.duckdb_execute_prepared_streaming(statement, c.byref(result))
        if status:
            error = api.duckdb_result_error(c.byref(result))
            observe("execute", "error", diagnostic_code(error))
        else:
            observe("execute", "ok")
            mode = "streaming" if api.duckdb_result_is_streaming(result) else "materialized"
            observe("result_mode", mode)
            while chunk_address := api.duckdb_fetch_chunk(result):
                chunk = c.c_void_p(chunk_address)
                try:
                    size = api.duckdb_data_chunk_get_size(chunk)
                    count += size
                    observe("chunk", "rows", str(size))
                finally:
                    api.duckdb_destroy_data_chunk(c.byref(chunk))
        error = api.duckdb_result_error(c.byref(result))
        if status or error:
            observe("result", "error", diagnostic_code(error))
        else:
            observe("result", "ok")
        observe("delivery", "rows", str(count))
        return error
    finally:
        api.duckdb_destroy_result(c.byref(result))


@contextmanager
def observation(case, invocation):
    sequence = 0

    def emit(event, outcome, value=""):
        nonlocal sequence
        print("\t".join(("QW_OBSERVATION", "1", case, invocation, str(sequence), event, outcome, value)))
        sequence += 1

    emit("start", "ok")
    yield emit
    emit("end", "ok")


def observe_host_scans(api, connection, graph, sql):
    for invocation, quota in (("host_valid", None), ("host_first_batch_error", 1)):
        with observation("observer.lifecycle", invocation) as emit:
            execute_setup(api, connection, provision(graph, max_batch_bytes=quota))
            with prepare(api, connection, sql, emit) as statement:
                count_delivered(api, statement, emit)


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def observe_path_swap(api, connection, graph, sql):
    with tempfile.TemporaryDirectory(prefix="qw-path-swap-", dir=graph.parent) as directory:
        scratch = Path(directory)
        source = scratch / "original.lbdb"
        held = scratch / "held.lbdb"
        replacement = scratch / "replacement.lbdb"
        shutil.copy2(graph, source)
        replacement.write_bytes(b"not a Ladybug graph")
        original_digest = digest(source)
        replacement_digest = digest(replacement)

        with observation("observer.policy", "corrupt_control") as emit:
            execute_setup(api, connection, provision(replacement))
            with prepare(api, connection, sql, emit) as statement:
                count_delivered(api, statement, emit)

        execute_setup(api, connection, provision(source))
        with observation("observer.policy", "path_swap") as emit:
            with prepare(api, connection, sql, emit) as statement:
                canonical_before = source.resolve(strict=True)
                source.replace(held)
                try:
                    source.symlink_to(replacement)
                    swapped = source.resolve(strict=True) != canonical_before
                    emit("path", "changed" if swapped else "unchanged")
                    error = count_delivered(api, statement, emit)
                    detail = b"Configured Ladybug path changed after binding"
                    matches = b"QW_ACCESS: " + detail in (error or b"")
                    emit("path_diagnostic", "observed" if matches else "missing",
                         detail.decode("ascii") if matches else "")
                finally:
                    try:
                        if source.is_symlink():
                            source.unlink()
                    finally:
                        held.replace(source)
                restored = source.resolve(strict=True) == canonical_before
                emit("path", "restored" if restored else "changed")
                count_delivered(api, statement, emit)
            original_after = digest(source)
            replacement_after = digest(replacement)
            emit("fixture_hash", "held_before", original_digest)
            emit("fixture_hash", "held_after", original_after)
            emit("fixture_hash", "replacement_before", replacement_digest)
            emit("fixture_hash", "replacement_after", replacement_after)
            unchanged = original_after == original_digest and replacement_after == replacement_digest
            emit("fixture", "unchanged" if unchanged else "changed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("duckdb-lib", "extension", "graph"):
        parser.add_argument("--" + flag, required=True, type=Path)
    args = parser.parse_args()
    graph = args.graph.resolve(strict=True)
    extension = args.extension.resolve(strict=True)
    api = duckdb_api(args.duckdb_lib)
    if api.duckdb_library_version() != DUCKDB_PIN_VERSION.encode():
        parser.error(f"DuckDB C API library {DUCKDB_PIN_VERSION} is required")
    call = graph_query(
        "MATCH (a:Document)-[:LINKS_TO]->(b:Document) WHERE a.id = 100 RETURN b.id AS document_id",
        dialect="gql",
    )
    with open_connection(api) as connection:
        execute_setup(api, connection, f"SELECT CASE WHEN source_id = '{DUCKDB_PIN_SOURCE}' THEN true "
                      "ELSE error('DuckDB C API library source ID mismatch') END FROM pragma_version();")
        execute_setup(api, connection, f"LOAD {sql_literal(extension)};")
        observe_host_scans(api, connection, graph, f"SELECT * FROM {call}")
        observe_path_swap(api, connection, graph, f"SELECT * FROM {call}")


if __name__ == "__main__":
    main()
