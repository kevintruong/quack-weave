"""Controls for the Ladybug connection-scoped Cypher lookup experiment."""
from time import perf_counter_ns

from adbc_driver_manager import dbapi
import pyarrow as pa

import run


KEYS = {"lookup": run.KEYS[0], "lookup_miss": -1}
PARAM_QUERY = "MATCH (p:Person) WHERE p.PersonId = $person_id RETURN p.PersonId AS id"
DIRECT_PREPARED = "direct_prepared_cypher"
DIRECT_PARAM = "direct_parameterized_cypher"
QW_PREPARED = "qw_prepared_match"
QW_PARAM = "qw_parameterized_match"
LIVE = "qw_prepared_session_scan"
FIXED = "qw_prepared_literal_scan"
CONTROLS = (DIRECT_PREPARED, QW_PREPARED, LIVE, FIXED, DIRECT_PARAM, QW_PARAM)
NATIVE_REFERENCE = {QW_PREPARED: DIRECT_PREPARED, LIVE: DIRECT_PREPARED,
                    FIXED: DIRECT_PREPARED, QW_PARAM: DIRECT_PARAM}


def scan_sql(route, query):
    arguments = ("current_setting('qw_selected_graph'), current_setting('qw_graph_dialect')"
                 if route == LIVE else f"{run.sql_literal(run.GRAPH_ALIAS)}, 'cypher'")
    return f"SELECT * FROM qw_graph_query({arguments}, {run.sql_literal(query)})"


def statement(route, query):
    if route in (DIRECT_PARAM, QW_PARAM):
        return PARAM_QUERY
    if route in (LIVE, FIXED):
        return scan_sql(route, query)
    return query


def prepare_fetch(stack, route, connection, statements, setup):
    """Allocate one handle per distinct client statement before warm-up."""
    start = perf_counter_ns()
    handles = {}
    calls = {}
    native = route in (DIRECT_PREPARED, DIRECT_PARAM)
    for name, original in statements.items():
        sql = statement(route, original)
        if sql not in handles:
            if native:
                handle = connection.prepare(sql)
                stack.callback(handle.close)
                if not handle.is_success():
                    raise ValueError(handle.get_error_message())
            else:
                handle = stack.enter_context(connection.cursor())
                handle.adbc_prepare(sql)
            handles[sql] = handle
        handle = handles[sql]
        if native:
            args = (handle, {"person_id": KEYS[name]}) if route == DIRECT_PARAM else (handle,)
        else:
            args = (sql, (KEYS[name],)) if route == QW_PARAM else (sql,)
        calls[original] = (handle, args)
    setup.update(prepare_ms=run.milliseconds(start), prepared_handles=len(handles))

    if native:
        def fetch(original):
            _, args = calls[original]
            with connection.execute(*args) as result:
                return result.get_as_arrow()
    else:
        def fetch(original):
            handle, args = calls[original]
            handle.execute(*args)
            return handle.fetch_arrow_table()
    return fetch


def probe_session(parent, route):
    """Test the binding after each mutation on the same handle, after all timed reads."""
    key = KEYS["lookup"]
    query = f"MATCH (p:Person {{PersonId: {key}}}) RETURN p.PersonId AS id"
    sql = scan_sql(route, query)
    observations = {}
    with parent.connection.cursor() as handle:
        handle.adbc_prepare(sql)

        def observe(change, expected):
            try:
                table = handle.execute(sql).fetch_arrow_table()
            except dbapi.Error as error:
                if expected == "hit" or expected + ":" not in str(error):
                    raise
                actual = expected
            else:
                if table.schema.names != ["id"] or table["id"].type != pa.int64() or table["id"].to_pylist() != [key]:
                    raise ValueError(f"{route} {change}: unexpected probe result {table}")
                actual = "hit"
            if actual != expected:
                raise ValueError(f"{route} {change}: expected {expected}, observed {actual}")
            observations[change] = actual

        observe("initial", "hit")
        parent.execute("SET SESSION qw_graph_dialect = 'gql'")
        observe("dialect_gql", "QW_GQL_SUBSET" if route == LIVE else "hit")
        parent.execute("SET SESSION qw_graph_dialect = 'cypher'")
        parent.execute("RESET qw_selected_graph")
        observe("graph_reset", "QW_CONFIG" if route == LIVE else "hit")
        parent.execute(f"SESSION SET GRAPH {run.GRAPH_ALIAS}")
        observe("restored", "hit")
        parent.execute("RESET GLOBAL qw_ladybug_config")
        observe("registration_reset", "QW_CONFIG")
    return {"statement": sql, "observations": observations}
