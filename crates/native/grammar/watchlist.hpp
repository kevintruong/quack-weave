#pragma once

#include "duckdb/parser/peg/ast/table_alias.hpp"
#include "duckdb/parser/query_node/select_node.hpp"
#include "duckdb/parser/tableref/joinref.hpp"

namespace duckdb {
class DatabaseInstance;

// Build a redundant provider predicate for a graph-side direct column in an
// inner equijoin. The caller retains the complete join and the original VALUES.
unique_ptr<ParsedExpression> QwWatchlistPredicate(const SelectNode &graph, const TableAlias &graph_alias,
                                                  const JoinRef &join, idx_t max_keys);

void QwRegisterWatchlistGuard(DatabaseInstance &db);
unique_ptr<ParsedExpression> QwGuardWatchlistQuery(const string &base, const string &candidate);

} // namespace duckdb
