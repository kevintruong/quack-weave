#include "c_api/lbug.h"
#include "parser/parser.h"
#include "parser/query/regular_query.h"

namespace {

using lbug::common::ClauseType;

template <typename Query>
bool has_only_graph_clauses(const Query& query) {
    if (query.getNumUpdatingClauses() != 0) {
        return false;
    }
    for (uint32_t index = 0; index < query.getNumReadingClauses(); ++index) {
        const auto type = query.getReadingClause(index)->getClauseType();
        if (type != ClauseType::MATCH && type != ClauseType::UNWIND) {
            return false;
        }
    }
    return true;
}

} // namespace

extern "C" lbug_state qw_ladybug_open_database(const char* path, bool read_only,
    lbug_database* database) noexcept {
    try {
        auto config = lbug_default_system_config();
        config.read_only = read_only;
        return lbug_database_init(path, config, database);
    } catch (...) {
        return LbugError;
    }
}

extern "C" bool qw_ladybug_is_graph_read(const char* text) noexcept {
    try {
        const auto statements = lbug::parser::Parser::parseQuery(text);
        if (statements.size() != 1 ||
            statements.front()->getStatementType() != lbug::common::StatementType::QUERY) {
            return false;
        }

        const auto& query = static_cast<const lbug::parser::RegularQuery&>(*statements.front());
        for (lbug::common::idx_t index = 0; index < query.getNumSingleQueries(); ++index) {
            const auto& part = *query.getSingleQuery(index);
            if (!part.hasReturnClause() || !has_only_graph_clauses(part)) {
                return false;
            }
            for (uint32_t part_index = 0; part_index < part.getNumQueryParts(); ++part_index) {
                if (!has_only_graph_clauses(*part.getQueryPart(part_index))) {
                    return false;
                }
            }
        }
        return query.getNumSingleQueries() != 0;
    } catch (...) {
        return false;
    }
}
