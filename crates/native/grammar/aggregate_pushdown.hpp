#pragma once

namespace duckdb {
class DatabaseInstance;
void QwRegisterAggregatePushdown(DatabaseInstance &db);
} // namespace duckdb
