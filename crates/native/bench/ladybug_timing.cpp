#include "c_api/lbug.h"
#include <cstdio>
#include <ctime>

static long long monotonic_ns() {
    timespec ts{};
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

extern "C" lbug_state qw_probe_execute(lbug_connection* conn, lbug_prepared_statement* statement,
                                       lbug_query_result* result) {
    const auto start = monotonic_ns();
    const auto state = lbug_connection_execute(conn, statement, result);
    const auto end = monotonic_ns();
    lbug_query_summary summary{};
    if (state == LbugSuccess && lbug_query_result_get_query_summary(result, &summary) == LbugSuccess) {
        std::fprintf(stderr, "QW_PHASE %lld %lld %.6f %.6f\n", start, end,
                     lbug_query_summary_get_compiling_time(&summary),
                     lbug_query_summary_get_execution_time(&summary));
        lbug_query_summary_destroy(&summary);
    }
    return state;
}
