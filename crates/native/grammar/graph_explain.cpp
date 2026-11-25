#include "graph_explain.hpp"

#include "duckdb/main/config.hpp"
#include "duckdb/optimizer/optimizer.hpp"
#include "duckdb/optimizer/optimizer_extension.hpp"
#include "duckdb/planner/operator/logical_get.hpp"

namespace duckdb {
namespace {
// to_string receives no ClientContext. Select a fixed callback on this bound
// scan and leave the C-v2 table function's own function_info and bind_data intact.
enum class Decision { Native, Base, Static, Runtime, Both, Aggregate, Limit, Catalog, Unsupported, Literal, HostJoin };

struct Description {
	const char *operation;
	const char *residual;
	const char *fallback;
};
constexpr Description DESCRIPTIONS[] = {
    {"Native graph read", nullptr, nullptr},
    {"Pattern scan", nullptr, nullptr},
    {"Static prefilter", "SQL predicate", nullptr},
    {"Optional runtime prefilter", "SQL join", nullptr},
    {"Static and optional runtime prefilters", "SQL predicate and join", nullptr},
    {"Delegated scalar aggregate", nullptr, nullptr},
    {"Pattern scan", nullptr, "Explicit resource limit"},
    {"Pattern scan", nullptr, "Declared property catalog"},
    {"Pattern scan", nullptr, "Unsupported relational operation"},
    {"Literal prefilter", "SQL join or predicate", nullptr},
    {"Pattern scan", "SQL join", "No eligible runtime key filter"},
};

template <bool RELATE, Decision DECISION>
InsertionOrderPreservingMap<string> Describe(TableFunctionToStringInput &input) {
	InsertionOrderPreservingMap<string> result;
	const auto &description = DESCRIPTIONS[static_cast<size_t>(DECISION)];
	result["Function"] = StringUtil::Upper(input.table_function.GetName().GetIdentifierName());
	result["Graph Provider"] = RELATE ? "RelateDB" : "Ladybug";
	result["Graph Operation"] = description.operation;
	if (description.residual)
		result["DuckDB Residual"] = description.residual;
	if (description.fallback)
		result["Fallback Reason"] = description.fallback;
	return result;
}

template <bool RELATE>
table_function_to_string_t Select(Decision decision) {
	static constexpr table_function_to_string_t CALLBACKS[] = {
	    Describe<RELATE, Decision::Native>, Describe<RELATE, Decision::Base>,
	    Describe<RELATE, Decision::Static>, Describe<RELATE, Decision::Runtime>,
	    Describe<RELATE, Decision::Both>, Describe<RELATE, Decision::Aggregate>,
	    Describe<RELATE, Decision::Limit>, Describe<RELATE, Decision::Catalog>,
	    Describe<RELATE, Decision::Unsupported>, Describe<RELATE, Decision::Literal>,
	    Describe<RELATE, Decision::HostJoin>};
	return CALLBACKS[static_cast<size_t>(decision)];
}

void DescribeScan(OptimizerExtensionInput &input, LogicalGet &get, LogicalOperatorType consumer) {
	auto &fn = get.function;
	if (fn.to_string || fn.GetCatalogName() != "system" || fn.GetSchemaName() != "main" ||
	    !fn.get_bind_info || !get.bind_data)
		return;
	const auto &name = fn.GetName();
	if (name != "qw_query" && name != "qw_graph_query" && name != "qw_graph_query_params" &&
	    name != "qw_graph_query_filtered" && name != "qw_graph_query_watch")
		return;
	TableFunctionGetBindInfoInput bind_input(input.context, get.bind_data.get());
	const auto info = fn.get_bind_info(bind_input);
	const auto provider = info.options.find("qw_provider");
	const auto route = info.options.find("qw_scan_mode");
	if (provider == info.options.end() || route == info.options.end())
		return;
	const auto mode = route->second.GetValue<string>();
	const bool runtime = get.dynamic_filters && fn.init_local != fn.GetDefinition()->init_local;
	Decision decision = Decision::Native;
	if (mode == "limit")
		decision = Decision::Limit;
	else if (mode == "catalog")
		decision = Decision::Catalog;
	else if (mode == "literal")
		decision = Decision::Literal;
	else if (mode == "static")
		decision = runtime ? Decision::Both : Decision::Static;
	else if (mode == "pattern") {
		decision = Decision::Base;
		if (runtime)
			decision = Decision::Runtime;
		else if (consumer == LogicalOperatorType::LOGICAL_COMPARISON_JOIN)
			decision = Decision::HostJoin;
		else if (consumer == LogicalOperatorType::LOGICAL_FILTER ||
		         consumer == LogicalOperatorType::LOGICAL_AGGREGATE_AND_GROUP_BY)
			decision = Decision::Unsupported;
	}
	fn.to_string = provider->second.GetValue<string>() == "RelateDB" ? Select<true>(decision) : Select<false>(decision);
}

void Annotate(OptimizerExtensionInput &input, unique_ptr<LogicalOperator> &plan) {
	vector<pair<LogicalOperator *, LogicalOperatorType>> pending {{plan.get(), LogicalOperatorType::LOGICAL_INVALID}};
	while (!pending.empty()) {
		const auto item = pending.back();
		pending.pop_back();
		auto &op = *item.first;
		if (op.type == LogicalOperatorType::LOGICAL_GET)
			DescribeScan(input, op.Cast<LogicalGet>(), item.second);
		// Attribute a residual only to its direct source through ordinary projections.
		const auto consumer = op.type == LogicalOperatorType::LOGICAL_PROJECTION ? item.second : op.type;
		for (auto &child : op.children)
			pending.emplace_back(child.get(), consumer);
	}
}
} // namespace

void QwMarkDelegatedAggregate(LogicalGet &get, bool relate) {
	get.function.to_string = relate ? Select<true>(Decision::Aggregate) : Select<false>(Decision::Aggregate);
}

void QwRegisterGraphExplain(DatabaseInstance &db) {
	OptimizerExtension extension;
	extension.optimize_function = Annotate;
	OptimizerExtension::Register(DBConfig::GetConfig(db), std::move(extension));
}
} // namespace duckdb
