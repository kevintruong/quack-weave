#include "aggregate_pushdown.hpp"

#include <limits>

#include "duckdb/main/config.hpp"
#include "duckdb/optimizer/optimizer.hpp"
#include "duckdb/optimizer/optimizer_extension.hpp"
#include "duckdb/parser/expression/constant_expression.hpp"
#include "duckdb/parser/expression/function_expression.hpp"
#include "duckdb/parser/tableref/table_function_ref.hpp"
#include "duckdb/planner/binder.hpp"
#include "duckdb/planner/bound_statement.hpp"
#include "duckdb/planner/expression/bound_aggregate_expression.hpp"
#include "duckdb/planner/expression/bound_cast_expression.hpp"
#include "duckdb/planner/expression/bound_columnref_expression.hpp"
#include "duckdb/planner/expression/bound_constant_expression.hpp"
#include "duckdb/planner/operator/logical_aggregate.hpp"
#include "duckdb/planner/operator/logical_get.hpp"
#include "duckdb/planner/operator/logical_projection.hpp"

namespace duckdb {
namespace {

bool IsSystem(const BoundSimpleFunction &fn) {
	return fn.GetCatalogName() == "system" && fn.GetSchemaName() == "main";
}

// The provider binder verifies the complete PGQ descriptor, including the
// native projection. Authored graph text has no such binding.
string GraphInput(const LogicalGet &scan, const BindInfo &info, bool relate, vector<string> &columns) {
	if (scan.table_filters.HasFilters() || scan.dynamic_filters || scan.extra_info.sample_options ||
	    scan.at_clause || scan.row_group_order_options || !scan.scan_partition_indices.empty() ||
	    scan.source_ordinality != OrdinalityType::WITHOUT_ORDINALITY || scan.ordinality_idx.IsValid() ||
	    !scan.projection_ids.empty() || !scan.children.empty())
		return "";
	const auto pattern = info.options.find("qw_match");
	const auto steps = info.options.find("qw_pattern_steps");
	const auto projection = info.options.find("qw_pgq_projection");
	if (pattern == info.options.end() || steps == info.options.end() || projection == info.options.end() ||
	    (relate && steps->second.GetValue<uint64_t>() > 1))
		return "";
	for (idx_t i = 0; i < scan.names.size(); ++i) {
		const auto slot = info.options.find("qw_property_" + std::to_string(i));
		if (slot == info.options.end())
			return "";
		columns.push_back(relate ? slot->second.GetValue<string>() : scan.names[i].GetIdentifierName());
	}
	const auto match = pattern->second.GetValue<string>();
	return relate ? match : match + " WITH " + projection->second.GetValue<string>();
}

// Follow bound references through purely relational column renames (including views).
string GraphColumn(ColumnBinding binding, const vector<const LogicalProjection *> &projections,
                   const LogicalGet &scan, const vector<string> &columns) {
	for (auto projection : projections) {
		if (binding.table_index != projection->table_index || binding.column_index >= projection->expressions.size())
			return "";
		binding = projection->expressions[binding.column_index]->Cast<BoundColumnRefExpression>().Binding();
	}
	if (binding.table_index != scan.table_index || binding.column_index >= scan.GetColumnIds().size())
		return "";
	auto &col = scan.GetColumnIndex(binding);
	if (!col.HasPrimaryIndex() || col.HasChildren() || col.GetPrimaryIndex() >= scan.names.size())
		return "";
	return columns[col.GetPrimaryIndex()];
}

string AggregateArgument(const Expression &expr, const vector<const LogicalProjection *> &projections,
                         const LogicalGet &scan, const vector<string> &columns, int64_t &divisor) {
	if (expr.GetReturnType() != LogicalType::BIGINT)
		return "";
	if (expr.GetExpressionClass() == ExpressionClass::BOUND_COLUMN_REF)
		return GraphColumn(expr.Cast<BoundColumnRefExpression>().Binding(), projections, scan, columns);
	if (expr.GetExpressionClass() != ExpressionClass::BOUND_FUNCTION)
		return "";
	auto &fn = expr.Cast<BoundFunctionExpression>();
	if (!IsSystem(fn.Function()) || fn.Function().GetName() != "%" || fn.GetChildren().size() != 2 ||
	    fn.GetChildren()[0]->GetExpressionClass() != ExpressionClass::BOUND_COLUMN_REF)
		return "";
	auto lhs = GraphColumn(fn.GetChildren()[0]->Cast<BoundColumnRefExpression>().Binding(), projections, scan, columns);
	const Expression *rhs = fn.GetChildren()[1].get();
	if (BoundCastExpression::IsCast(*rhs))
		rhs = &BoundCastExpression::Child(rhs->Cast<BoundFunctionExpression>());
	if (lhs.empty() || rhs->GetExpressionClass() != ExpressionClass::BOUND_CONSTANT)
		return "";
	auto &value = rhs->Cast<BoundConstantExpression>().GetValue();
	if (value.IsNull() || !(value.type() == LogicalType::BIGINT || value.type() == LogicalType::INTEGER))
		return "";
	divisor = value.GetValue<int64_t>();
	if (divisor <= 0)
		return ""; // Ladybug and DuckDB can differ for zero and BIGINT_MIN % -1.
	return lhs + " % " + std::to_string(divisor);
}

// Both bind calls must refer to the same registration. An explicit resource limit
// also precludes changing the provider's query and output batch boundaries.
BindInfo GraphBindInfo(ClientContext &context, LogicalGet &get) {
	if (!get.bind_data || !get.function.get_bind_info)
		return BindInfo(ScanType::EXTERNAL);
	TableFunctionGetBindInfoInput input(context, get.bind_data.get());
	return get.function.get_bind_info(input);
}

optional_idx AggregateGeneration(const BindInfo &info) {
	auto entry = info.options.find("qw_aggregate_generation");
	return entry == info.options.end() ? optional_idx() : optional_idx(entry->second.GetValue<uint64_t>());
}

void PushAggregate(OptimizerExtensionInput &input, unique_ptr<LogicalOperator> &plan) {
	auto &aggregate = plan->Cast<LogicalAggregate>();
	if (!aggregate.groups.empty() || !aggregate.grouping_sets.empty() || !aggregate.grouping_functions.empty() ||
	    aggregate.children.size() != 1 || aggregate.expressions.empty())
		return;
	auto source = aggregate.children.front().get();
	vector<const LogicalProjection *> projections;
	while (source->type == LogicalOperatorType::LOGICAL_PROJECTION && source->children.size() == 1) {
		for (auto &expr : source->expressions)
			if (expr->GetExpressionClass() != ExpressionClass::BOUND_COLUMN_REF ||
			    expr->Cast<BoundColumnRefExpression>().Depth() != 0)
				return;
		projections.push_back(&source->Cast<LogicalProjection>());
		source = source->children.front().get();
	}
	if (source->type != LogicalOperatorType::LOGICAL_GET)
		return;
	auto &scan = source->Cast<LogicalGet>();
	if (!IsSystem(scan.function) || scan.function.GetName() != "qw_graph_query")
		return;
	auto info = GraphBindInfo(input.context, scan);
	auto generation = AggregateGeneration(info);
	if (!generation.IsValid())
		return;
	const auto bound = info.options.find("qw_single_pattern_row_bound");
	const bool relate = bound != info.options.end();
	const auto max_rows = relate ? bound->second.GetValue<uint64_t>() : 0;
	vector<string> columns;
	const auto graph = GraphInput(scan, info, relate, columns);
	if (graph.empty())
		return;
	vector<string> fields, schema;
	vector<LogicalType> types;
	for (auto &expr : aggregate.expressions) {
		const auto &aggr = expr->Cast<BoundAggregateExpression>();
		if (aggr.IsDistinct() || aggr.GetFilter() || aggr.GetOrderBys() ||
		    aggr.StateExportMode() != AggregateStateExportMode::NONE || !IsSystem(aggr.Function()))
			return;
		const auto &name = aggr.Function().GetName();
		string field, ty;
		if (name == "count_star" && aggr.GetChildren().empty() && expr->GetReturnType() == LogicalType::BIGINT) {
			field = "count(*)";
			ty = "BIGINT";
		} else if ((name == "sum" || name == "count") && aggr.GetChildren().size() == 1) {
			int64_t divisor = 0;
			auto arg = AggregateArgument(*aggr.GetChildren()[0], projections, scan, columns, divisor);
			if (arg.empty())
				return;
			if (name == "sum" && expr->GetReturnType() == LogicalType::HUGEINT && relate) {
				// Relate promotes overflowing integer sums to FLOAT and returns zero on
				// empty input. Prove every partial sum fits i64 before delegating it.
				if (!divisor || (max_rows && uint64_t(divisor - 1) >
				                    uint64_t(std::numeric_limits<int64_t>::max()) / max_rows))
					return;
				field = "CASE WHEN count(" + arg + ") = 0 THEN NULL ELSE sum(" + arg + ") END";
				ty = "BIGINT";
			} else if (name == "sum" && expr->GetReturnType() == LogicalType::HUGEINT) {
				// Ladybug sums INT64 to INT128. Its lossless decimal text fits the existing
				// provider schema; only one scalar per SUM crosses the boundary.
				field = "CAST(sum(" + arg + ") AS STRING)";
				ty = "VARCHAR";
			} else if (name == "count" && expr->GetReturnType() == LogicalType::BIGINT) {
				field = "count(" + arg + ")";
				ty = "BIGINT";
			} else
				return;
		} else
			return;
		const auto alias = "qw_agg" + std::to_string(fields.size());
		fields.push_back(field + " AS " + alias);
		schema.push_back(alias + " " + ty);
		types.push_back(expr->GetReturnType());
	}
	vector<FunctionArgument> args;
	args.emplace_back(ConstantExpression::String(scan.parameters[0].ToString()));
	args.emplace_back(ConstantExpression::String("cypher"));
	args.emplace_back(ConstantExpression::String(graph + " RETURN " + StringUtil::Join(fields, ", ")));
	auto schema_arg = ConstantExpression::String(StringUtil::Join(schema, ", "));
	schema_arg->SetAlias(Identifier("schema"));
	args.emplace_back(std::move(schema_arg));
	TableFunctionRef ref;
	ref.function = make_uniq<FunctionExpression>(QualifiedName("system", "main", "qw_query"), std::move(args));
	auto binder = Binder::CreateBinder(input.context, input.optimizer.binder);
	BoundStatement replacement;
	try {
		replacement = binder->Bind(static_cast<TableRef &>(ref));
	} catch (const InvalidInputException &) {
		// A new registration or reset can race with binding the replacement.
		return;
	}
	auto &get = replacement.plan->Cast<LogicalGet>();
	auto rebound = AggregateGeneration(GraphBindInfo(input.context, get));
	if (!rebound.IsValid() || rebound.GetIndex() != generation.GetIndex())
		return;
	get.ClearColumnIds();
	vector<unique_ptr<Expression>> results;
	for (idx_t i = 0; i < types.size(); ++i) {
		auto binding = ColumnBinding(get.table_index, get.AddColumnId(i));
		auto read = make_uniq<BoundColumnRefExpression>(get.returned_types[i], binding);
		results.push_back(BoundCastExpression::AddDefaultCastToType(std::move(read), types[i]));
	}
	// Retain the output bindings expected by parents, including nested CTEs and HAVING.
	auto project = make_uniq<LogicalProjection>(aggregate.aggregate_index, std::move(results));
	project->children.push_back(std::move(replacement.plan));
	plan = std::move(project);
}

void OptimizeAggregates(OptimizerExtensionInput &input, unique_ptr<LogicalOperator> &root) {
	vector<unique_ptr<LogicalOperator> *> pending {&root};
	while (!pending.empty()) {
		auto plan = pending.back();
		pending.pop_back();
		if ((*plan)->type == LogicalOperatorType::LOGICAL_AGGREGATE_AND_GROUP_BY)
			PushAggregate(input, *plan);
		for (auto &child : (*plan)->children)
			pending.push_back(&child);
	}
}

} // namespace

void QwRegisterAggregatePushdown(DatabaseInstance &db) {
	OptimizerExtension extension;
	extension.pre_optimize_function = OptimizeAggregates;
	OptimizerExtension::Register(DBConfig::GetConfig(db), std::move(extension));
}
} // namespace duckdb
