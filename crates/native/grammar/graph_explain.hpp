#pragma once

namespace duckdb {
class DatabaseInstance;
class LogicalGet;
void QwMarkDelegatedAggregate(LogicalGet &get, bool relate);
void QwRegisterGraphExplain(DatabaseInstance &db);
} // namespace duckdb
