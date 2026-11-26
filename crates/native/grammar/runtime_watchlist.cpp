#include "watchlist.hpp"

#include "duckdb/execution/operator/scan/physical_table_scan.hpp"
#include "duckdb/logging/log_manager.hpp"
#include "duckdb/logging/logger.hpp"
#include "duckdb/main/database.hpp"
#include "duckdb/optimizer/join_filter_pushdown_optimizer.hpp"
#include "duckdb/optimizer/optimizer.hpp"
#include "duckdb/optimizer/optimizer_extension.hpp"
#include "duckdb/planner/expression/bound_columnref_expression.hpp"
#include "duckdb/planner/expression/bound_conjunction_expression.hpp"
#include "duckdb/planner/expression/bound_constant_expression.hpp"
#include "duckdb/planner/expression/bound_function_expression.hpp"
#include "duckdb/planner/expression/bound_operator_expression.hpp"
#include "duckdb/planner/expression/bound_reference_expression.hpp"
#include "duckdb/planner/filter/expression_filter.hpp"
#include "duckdb/planner/operator/logical_comparison_join.hpp"
#include "duckdb/planner/operator/logical_get.hpp"
#include "duckdb/planner/operator/logical_projection.hpp"

namespace duckdb {
namespace {
constexpr const char *WATCHLIST_LOG_TYPE = "QuackWeaveWatchlist";

// Ordered by preference when the scan asks about more than one slot.
enum class KeyOffer { NotRequested, NoExactKeys, OverCap, ExactKeys };

struct WatchInit {
	const TableFunctionInitInput &input;
	KeyOffer offer = KeyOffer::NotRequested;

	void Observe(KeyOffer next) {
		if (next > offer)
			offer = next;
	}
};

// The v2 C table-function API doesn't expose dynamic scan filters. Forward them
// only during its synchronous init_local callback. Rust copies the bounded keys
// into this scan's local state before it returns, including on prepared plans.
thread_local WatchInit *active_watch = nullptr;

void LogKeyOffer(ExecutionContext &context, KeyOffer offer) noexcept {
	if (offer == KeyOffer::NotRequested)
		return;
	const char *message = "no_exact_keys";
	if (offer == KeyOffer::OverCap)
		message = "key_cap";
	else if (offer == KeyOffer::ExactKeys)
		message = "exact_keys";
	try {
		DUCKDB_LOG_INTERNAL(context, WATCHLIST_LOG_TYPE, LogLevel::LOG_INFO, message);
	} catch (...) {
		// Diagnostics cannot change query execution if a log sink fails.
	}
}

unique_ptr<LocalTableFunctionState> InitWatch(ExecutionContext &context, TableFunctionInitInput &input,
                                              GlobalTableFunctionState *global) {
	const auto &scan = input.op->Cast<PhysicalTableScan>();
	const auto original_init = scan.function.GetDefinition()->init_local;
	WatchInit watch {input};
	unique_ptr<LocalTableFunctionState> result;
	{
		struct Restore {
			WatchInit *previous;
			~Restore() {
				active_watch = previous;
			}
		} restore {active_watch};
		active_watch = &watch;
		result = original_init(context, input, global);
	}
	LogKeyOffer(context, watch.offer);
	return result;
}

// Follow only column renames. Moving a predicate past a throwing or volatile
// projection on unrelated rows could change the visible result of the query.
LogicalGet *WatchSource(LogicalOperator &probe) {
	auto *op = &probe;
	while (op->type == LogicalOperatorType::LOGICAL_PROJECTION && op->children.size() == 1) {
		for (const auto &expr : op->expressions) {
			if (expr->GetExpressionClass() != ExpressionClass::BOUND_COLUMN_REF)
				return nullptr;
		}
		op = op->children.front().get();
	}
	return op->type == LogicalOperatorType::LOGICAL_GET ? &op->Cast<LogicalGet>() : nullptr;
}

void AttachWatch(OptimizerExtensionInput &input, LogicalOperator &op) {
	if (op.type != LogicalOperatorType::LOGICAL_COMPARISON_JOIN)
		return;
	auto &join = op.Cast<LogicalComparisonJoin>();
	if (join.join_type != JoinType::INNER || join.conditions.size() != 1 || !join.conditions[0].IsComparison() ||
	    join.conditions[0].GetComparisonType() != ExpressionType::COMPARE_EQUAL ||
	    join.conditions[0].GetLHS().GetReturnType() != LogicalType::BIGINT ||
	    join.children[1]->type != LogicalOperatorType::LOGICAL_GET || !join.children[1]->Cast<LogicalGet>().GetTable())
		return;
	auto graph = WatchSource(*join.children[0]);
	if (!graph || !graph->children.empty() || graph->function.GetCatalogName() != "system" ||
	    graph->function.GetSchemaName() != "main" ||
	    (graph->function.GetName() != "qw_graph_query" && graph->function.GetName() != "qw_graph_query_watch") ||
	    !graph->function.GetDefinition()->init_local || graph->function.init_local != graph->function.GetDefinition()->init_local ||
	    !graph->bind_data || !graph->function.get_bind_info || graph->dynamic_filters || graph->table_filters.HasFilters())
		return;

	TableFunctionGetBindInfoInput bind_input(input.context, graph->bind_data.get());
	auto info = graph->function.get_bind_info(bind_input);
	if (info.options.find("qw_match") == info.options.end() && info.options.find("qw_runtime_watch") == info.options.end())
		return;

	// The pinned C API exposes bound static filters, but only the C++ init
	// callback exposes DuckDB's execution-local dynamic filter set.
	const auto previous = graph->function.filter_pushdown;
	graph->function.filter_pushdown = true;
	JoinFilterPushdownOptimizer(input.optimizer).VisitOperator(join);
	graph->function.filter_pushdown = previous;
	if (graph->dynamic_filters)
		graph->function.init_local = InitWatch;
}

struct KeyCopy {
	KeyOffer offer = KeyOffer::NoExactKeys;
	size_t count = 0;
};

KeyCopy CopyKeys(const Expression &expr, int64_t *out, size_t cap) {
	if (auto child = ExpressionFilter::GetOptionalFilterChild(expr)) {
		return CopyKeys(*child, out, cap);
	}
	if (expr.GetExpressionType() == ExpressionType::CONJUNCTION_AND &&
	    expr.GetExpressionClass() == ExpressionClass::BOUND_CONJUNCTION) {
		KeyCopy best;
		for (const auto &child : expr.Cast<BoundConjunctionExpression>().GetChildren()) {
			const auto keys = CopyKeys(*child, out, cap);
			if (keys.count)
				return keys;
			if (keys.offer == KeyOffer::OverCap)
				best = keys;
		}
		return best;
	}
	if (expr.GetExpressionType() == ExpressionType::COMPARE_EQUAL &&
	    expr.GetExpressionClass() == ExpressionClass::BOUND_FUNCTION && cap) {
		auto comparison = ExpressionType::INVALID;
		auto constant =
		    ExpressionFilter::TryGetColumnConstantComparison(expr.Cast<BoundFunctionExpression>(), comparison);
		if (constant && constant->GetValue().type() == LogicalType::BIGINT && !constant->GetValue().IsNull()) {
			out[0] = BigIntValue::Get(constant->GetValue());
			return {KeyOffer::ExactKeys, 1};
		}
	}
	if (expr.GetExpressionType() != ExpressionType::COMPARE_IN ||
	    expr.GetExpressionClass() != ExpressionClass::BOUND_OPERATOR)
		return {};
	const auto &items = expr.Cast<BoundOperatorExpression>().GetChildren();
	if (items.size() < 2 || items[0]->GetExpressionClass() != ExpressionClass::BOUND_REF ||
	    items[0]->GetReturnType() != LogicalType::BIGINT || items[0]->Cast<BoundReferenceExpression>().Index() != 0)
		return {};
	const auto count = items.size() - 1;
	// DuckDB constructs this runtime IN offer from the join key column. In the
	// over-cap case, report its size class without inspecting or copying keys.
	if (count > cap)
		return {KeyOffer::OverCap, 0};
	for (idx_t i = 1; i < items.size(); i++) {
		if (items[i]->GetExpressionClass() != ExpressionClass::BOUND_CONSTANT)
			return {};
		auto &value = items[i]->Cast<BoundConstantExpression>().GetValue();
		if (value.type() != LogicalType::BIGINT || value.IsNull())
			return {};
		out[i - 1] = BigIntValue::Get(value);
	}
	return {KeyOffer::ExactKeys, count};
}
} // namespace

void QwRegisterRuntimeWatchlist(DatabaseInstance &db) {
	db.GetLogManager().RegisterLogType(make_uniq<LogType>(WATCHLIST_LOG_TYPE, LogLevel::LOG_INFO));
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
	if (!active_watch)
		return 0;
	auto &watch = *active_watch;
	const auto &input = watch.input;
	watch.Observe(KeyOffer::NoExactKeys);
	try {
		if (!input.filters)
			return 0;
		for (idx_t i = 0; i < input.column_ids.size(); ++i) {
			if (input.column_ids[i] != column)
				continue;
			auto filter = input.filters->TryGetFilterByColumnIndex(ProjectionIndex(i));
			if (filter && filter->filter_type == TableFilterType::EXPRESSION_FILTER) {
				const auto keys = CopyKeys(*filter->Cast<ExpressionFilter>().expr, out, cap);
				watch.Observe(keys.offer);
				return keys.count;
			}
		}
	} catch (...) {
		// This read is an optional prefilter; the unchanged join enforces correctness.
	}
	return 0;
}
