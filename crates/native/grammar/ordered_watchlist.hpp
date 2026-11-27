#pragma once

#include "duckdb/common/limits.hpp"
#include "duckdb/planner/expression/bound_columnref_expression.hpp"
#include "duckdb/planner/operator/logical_comparison_join.hpp"
#include "duckdb/planner/operator/logical_get.hpp"
#include "duckdb/planner/operator/logical_projection.hpp"
#include "duckdb/planner/operator/logical_top_n.hpp"

namespace duckdb {

// The bound function carries a plan-local offer to physical scan init. It
// leaves the registered v2 function definition and its bind data in place.
struct QwOrderedWatchlistOffer final : TableFunctionInfo {
	QwOrderedWatchlistOffer(column_t order_column, column_t join_column, idx_t limit)
	    : order_column(order_column), join_column(join_column), limit(limit) {
	}
	column_t order_column;
	column_t join_column;
	idx_t limit;
};

namespace qw_ordered_watchlist {

inline bool DirectBigInt(const Expression &expr) {
	return expr.GetExpressionClass() == ExpressionClass::BOUND_COLUMN_REF &&
	       expr.GetReturnType() == LogicalType::BIGINT && expr.Cast<BoundColumnRefExpression>().Depth() == 0;
}

inline LogicalOperator *TraceRenames(LogicalOperator &input, ColumnBinding &binding, ColumnBinding *other = nullptr) {
	auto *source = &input;
	while (source->type == LogicalOperatorType::LOGICAL_PROJECTION && source->children.size() == 1) {
		auto &projection = source->Cast<LogicalProjection>();
		for (const auto &expr : projection.expressions) {
			if (expr->GetExpressionClass() != ExpressionClass::BOUND_COLUMN_REF ||
			    expr->Cast<BoundColumnRefExpression>().Depth() != 0)
				return nullptr;
		}
		auto trace = [&](ColumnBinding &column) {
			if (column.table_index != projection.table_index || column.column_index >= projection.expressions.size())
				return false;
			column = projection.expressions[column.column_index]->Cast<BoundColumnRefExpression>().Binding();
			return true;
		};
		if (!trace(binding) || (other && !trace(*other)))
			return nullptr;
		source = source->children.front().get();
	}
	return source;
}

inline optional_idx BigIntSlot(const LogicalGet &scan, ColumnBinding binding) {
	if (binding.table_index != scan.table_index || binding.column_index >= scan.GetColumnIds().size())
		return {};
	const auto &column = scan.GetColumnIndex(binding);
	if (!column.HasPrimaryIndex() || column.HasChildren() || column.GetPrimaryIndex() >= scan.returned_types.size() ||
	    scan.returned_types[column.GetPrimaryIndex()] != LogicalType::BIGINT)
		return {};
	return optional_idx(column.GetPrimaryIndex());
}

inline void Offer(LogicalTopN &top) {
	if (top.children.size() != 1 || top.orders.size() != 1 || top.offset || top.unpruned_offset.IsValid() || !top.limit ||
	    top.limit > static_cast<idx_t>(NumericLimits<int64_t>::Maximum()))
		return;
	auto &order = top.orders[0];
	if (order.type != OrderType::ASCENDING || order.null_order != OrderByNullType::NULLS_LAST ||
	    !DirectBigInt(*order.expression))
		return;
	auto order_binding = order.expression->Cast<BoundColumnRefExpression>().Binding();
	const auto outputs = top.GetColumnBindings();
	// Equal sort keys can be chosen in either order only when their observable
	// values are identical. The ordering value is the only visible output.
	if (outputs.size() != 1 || outputs[0] != order_binding)
		return;
	auto *source = TraceRenames(*top.children[0], order_binding);
	if (!source || source->type != LogicalOperatorType::LOGICAL_COMPARISON_JOIN || source->children.size() != 2)
		return;
	auto &join = source->Cast<LogicalComparisonJoin>();
	if (join.join_type != JoinType::INNER || join.conditions.size() != 1)
		return;
	auto &condition = join.conditions[0];
	if (!condition.IsComparison() || condition.GetComparisonType() != ExpressionType::COMPARE_EQUAL ||
	    !DirectBigInt(condition.GetLHS()) || !DirectBigInt(condition.GetRHS()))
		return;
	auto &watch = *join.children[1];
	if (watch.type != LogicalOperatorType::LOGICAL_GET || !watch.Cast<LogicalGet>().GetTable())
		return;
	const auto watch_binding = condition.GetRHS().Cast<BoundColumnRefExpression>().Binding();
	if (!BigIntSlot(watch.Cast<LogicalGet>(), watch_binding).IsValid())
		return;
	auto join_binding = condition.GetLHS().Cast<BoundColumnRefExpression>().Binding();
	auto *graph = TraceRenames(*join.children[0], order_binding, &join_binding);
	if (!graph || graph->type != LogicalOperatorType::LOGICAL_GET)
		return;
	auto &scan = graph->Cast<LogicalGet>();
	if (scan.function.GetCatalogName() != "system" || scan.function.GetSchemaName() != "main" ||
	    scan.function.GetName() != "qw_graph_query" || !scan.children.empty() || scan.table_filters.HasFilters() ||
	    scan.table_filters.HasMultiColumnFilters() || scan.extra_info.sample_options || scan.at_clause ||
	    scan.source_ordinality != OrdinalityType::WITHOUT_ORDINALITY || scan.ordinality_idx.IsValid())
		return;
	const auto order_column = BigIntSlot(scan, order_binding);
	const auto join_column = BigIntSlot(scan, join_binding);
	if (order_column.IsValid() && join_column.IsValid())
		scan.function.function_info = make_shared_ptr<QwOrderedWatchlistOffer>(order_column.GetIndex(),
		                                                                    join_column.GetIndex(), top.limit);
}

} // namespace qw_ordered_watchlist
} // namespace duckdb
