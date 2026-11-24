#pragma once

#include "duckdb/parser/grammar_change.hpp"

namespace duckdb {

void QwAddGraphTableRules(vector<GrammarChange> &changes);

} // namespace duckdb
