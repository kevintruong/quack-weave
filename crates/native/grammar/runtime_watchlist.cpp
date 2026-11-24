#include "watchlist.hpp"

#include "duckdb/execution/operator/scan/physical_table_scan.hpp"
#include "duckdb/main/database.hpp"
#include "duckdb/optimizer/join_filter_pushdown_optimizer.hpp"
#include "duckdb/optimizer/optimizer.hpp"
#include "duckdb/optimizer/optimizer_extension.hpp"
#include "duckdb/planner/expression/bound_conjunction_expression.hpp"
#include "duckdb/planner/expression/bound_constant_expression.hpp"
#include "duckdb/planner/expression/bound_function_expression.hpp"
#include "duckdb/planner/expression/bound_operator_expression.hpp"
#include "duckdb/planner/expression/bound_reference_expression.hpp"
#include "duckdb/planner/filter/expression_filter.hpp"
#include "duckdb/planner/operator/logical_comparison_join.hpp"
#include "duckdb/planner/operator/logical_get.hpp"

namespace duckdb {
namespace {
// The v2 C table-function API doesn't expose dynamic scan filters. Forward them
// only during its synchronous init_local callback. Rust copies the bounded keys
// into this scan's local state before it returns, including on prepared plans.
thread_local const TableFunctionInitInput *active_input = nullptr;

unique_ptr<LocalTableFunctionState> InitWatch(ExecutionContext &context, TableFunctionInitInput &input,
                                              GlobalTableFunctionState *global) {
	const auto &scan = input.op->Cast<PhysicalTableScan>();
	const auto original_init = scan.function.GetDefinition()->init_local;
	struct Restore {
		const TableFunctionInitInput *previous;
		~Restore() {
			active_input = previous;
		}
	} restore {active_input};
	active_input = &input;
	return original_init(context, input, global);
}

void AttachWatch(OptimizerExtensionInput &input, LogicalOperator &op) {
	if (op.type != LogicalOperatorType::LOGICAL_COMPARISON_JOIN) {
		return;
	}
	auto &join = op.Cast<LogicalComparisonJoin>();
	if (join.join_type != JoinType::INNER || join.conditions.size() != 1 || !join.conditions[0].IsComparison() ||
	    join.conditions[0].GetComparisonType() != ExpressionType::COMPARE_EQUAL ||
	    join.children[0]->type != LogicalOperatorType::LOGICAL_GET ||
	    join.children[1]->type != LogicalOperatorType::LOGICAL_GET) {
		return;
	}
	auto &graph = join.children[0]->Cast<LogicalGet>();
	auto &watch = join.children[1]->Cast<LogicalGet>();
	if (graph.function.GetName() != "qw_graph_query_watch" || graph.function.GetCatalogName() != "system" ||
	    graph.function.GetSchemaName() != "main" || !graph.function.GetDefinition()->init_local ||
	    graph.function.init_local != graph.function.GetDefinition()->init_local || !watch.GetTable() ||
	    !graph.children.empty() || !watch.children.empty() || graph.function.init_local == InitWatch ||
	    graph.dynamic_filters || graph.table_filters.HasFilters()) {
		return;
	}
	// DuckDB propagates dynamic filters to the physical scan only for
	// projection_pushdown sources. The C API implementation writes a complete
	// schema, so opt in only when the requested output is exactly that schema.
	const auto &columns = graph.GetColumnIds();
	if (columns.size() != graph.returned_types.size() || !graph.projection_ids.empty())
		return;
	for (idx_t i = 0; i < columns.size(); ++i) {
		if (columns[i].IsVirtualColumn() || columns[i].GetPrimaryIndex() != i || columns[i].HasChildren())
			return;
	}
	// Only optional hash-join filters can enter this source. Static filters
	// were already planned with filter_pushdown=false and remain in DuckDB.
	graph.function.filter_pushdown = true;
	JoinFilterPushdownOptimizer(input.optimizer).VisitOperator(join);
	graph.function.filter_pushdown = false;
	if (graph.dynamic_filters) {
		graph.function.projection_pushdown = true;
		graph.function.init_local = InitWatch;
	}
}

size_t CopyKeys(const Expression &expr, int64_t *out, size_t cap) {
	if (auto child = ExpressionFilter::GetOptionalFilterChild(expr)) {
		return CopyKeys(*child, out, cap);
	}
	if (expr.GetExpressionType() == ExpressionType::CONJUNCTION_AND &&
	    expr.GetExpressionClass() == ExpressionClass::BOUND_CONJUNCTION) {
		for (const auto &child : expr.Cast<BoundConjunctionExpression>().GetChildren()) {
			if (auto n = CopyKeys(*child, out, cap))
				return n;
		}
	}
	if (expr.GetExpressionType() == ExpressionType::COMPARE_EQUAL &&
	    expr.GetExpressionClass() == ExpressionClass::BOUND_FUNCTION && cap) {
		auto comparison = ExpressionType::INVALID;
		auto constant =
		    ExpressionFilter::TryGetColumnConstantComparison(expr.Cast<BoundFunctionExpression>(), comparison);
		if (constant && constant->GetValue().type() == LogicalType::BIGINT && !constant->GetValue().IsNull()) {
			out[0] = BigIntValue::Get(constant->GetValue());
			return 1;
		}
	}
	if (expr.GetExpressionType() != ExpressionType::COMPARE_IN ||
	    expr.GetExpressionClass() != ExpressionClass::BOUND_OPERATOR)
		return 0;
	const auto &items = expr.Cast<BoundOperatorExpression>().GetChildren();
	if (items.size() < 2 || items.size() - 1 > cap || items[0]->GetExpressionClass() != ExpressionClass::BOUND_REF ||
	    items[0]->GetReturnType() != LogicalType::BIGINT || items[0]->Cast<BoundReferenceExpression>().Index() != 0)
		return 0;
	for (idx_t i = 1; i < items.size(); i++) {
		if (items[i]->GetExpressionClass() != ExpressionClass::BOUND_CONSTANT)
			return 0;
		auto &value = items[i]->Cast<BoundConstantExpression>().GetValue();
		if (value.type() != LogicalType::BIGINT || value.IsNull())
			return 0;
		out[i - 1] = BigIntValue::Get(value);
	}
	return items.size() - 1;
}
} // namespace

void QwRegisterRuntimeWatchlist(DatabaseInstance &db) {
	OptimizerExtension ext;
	ext.optimize_function = [](OptimizerExtensionInput &input, unique_ptr<LogicalOperator> &plan) {
		if (input.optimizer.OptimizerDisabled(OptimizerType::JOIN_FILTER_PUSHDOWN))
			return;
		vector<reference<LogicalOperator>> pending {*plan};
		while (!pending.empty()) {
			auto &op = pending.back().get();
			pending.pop_back();
			if (op.type == LogicalOperatorType::LOGICAL_RECURSIVE_CTE)
				continue;
			AttachWatch(input, op);
			for (auto &child : op.children)
				pending.push_back(*child);
		}
	};
	OptimizerExtension::Register(DBConfig::GetConfig(db), std::move(ext));
}
} // namespace duckdb

extern "C" size_t qw_runtime_watch_keys(size_t column, int64_t *out, size_t cap) noexcept {
	using namespace duckdb;
	try {
		if (!active_input || !active_input->filters)
			return 0;
		for (idx_t i = 0; i < active_input->column_ids.size(); ++i) {
			if (active_input->column_ids[i] != column)
				continue;
			auto filter = active_input->filters->TryGetFilterByColumnIndex(ProjectionIndex(i));
			if (filter && filter->filter_type == TableFilterType::EXPRESSION_FILTER) {
				return CopyKeys(*filter->Cast<ExpressionFilter>().expr, out, cap);
			}
		}
	} catch (...) {
		// This read is an optional prefilter; the unchanged join enforces correctness.
	}
	return 0;
}
