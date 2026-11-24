#include "watchlist.hpp"

#include "duckdb/catalog/catalog.hpp"
#include "duckdb/catalog/entry_lookup_info.hpp"
#include "duckdb/main/extension/extension_loader.hpp"
#include "duckdb/parser/expression/function_expression.hpp"
#include "duckdb/planner/binder.hpp"
#include "duckdb/planner/expression/bound_constant_expression.hpp"
#include "duckdb/parser/expression/cast_expression.hpp"
#include "duckdb/parser/expression/columnref_expression.hpp"
#include "duckdb/parser/expression/comparison_expression.hpp"
#include "duckdb/parser/expression/constant_expression.hpp"
#include "duckdb/parser/expression/operator_expression.hpp"
#include "duckdb/parser/expression/type_expression.hpp"
#include "duckdb/parser/statement/select_statement.hpp"
#include "duckdb/parser/tableref/expressionlistref.hpp"
#include "duckdb/parser/tableref/subqueryref.hpp"
#include "duckdb/parser/expression/star_expression.hpp"

namespace duckdb {
namespace {

const ParsedExpression *DirectProperty(const SelectNode &graph, const TableAlias &alias, const Identifier &column) {
	const ParsedExpression *result = nullptr;
	identifier_set_t projected_names;
	for (idx_t i = 0; i < graph.select_list.size(); ++i) {
		const auto &expr = *graph.select_list[i];
		// Filtering before a volatile or throwing projection can change SQL behavior.
		if (expr.GetExpressionClass() != ExpressionClass::COLUMN_REF) {
			return nullptr;
		}
		const auto output_name = i < alias.column_name_alias.size() ? alias.column_name_alias[i]
		                         : expr.HasAlias()                  ? expr.GetAlias()
		                                                            : expr.GetName();
		if (!projected_names.insert(output_name).second) {
			return nullptr;
		}
		if (output_name == column) {
			result = &expr;
		}
	}
	return result;
}

const Literal *IntegerOrNull(const ParsedExpression &expr, bool &negated) {
	auto child = &expr;
	if (expr.GetExpressionClass() == ExpressionClass::FUNCTION) {
		const auto &fn = expr.Cast<FunctionExpression>();
		if (!fn.IsOperator() || fn.FunctionName() != "-" || fn.GetArguments().size() != 1) {
			return nullptr;
		}
		child = &fn.GetArguments()[0].GetExpression();
		negated = true;
	}
	if (child->GetExpressionClass() == ExpressionClass::CAST) {
		const auto &cast = child->Cast<CastExpression>();
		const auto &target = cast.TargetType();
		if (!target.GetCatalog().empty() || !target.GetSchema().empty() || !target.GetChildren().empty() ||
		    target.GetTypeName() != "BIGINT" || cast.IsTryCast()) {
			return nullptr;
		}
		child = &cast.Child();
	}
	if (child->GetExpressionClass() != ExpressionClass::CONSTANT) {
		return nullptr;
	}
	return &child->Cast<ConstantExpression>().GetLiteral();
}

} // namespace

const ParsedExpression *QwTableWatchKey(const SelectNode &graph, const TableAlias &alias, const JoinRef &join) {
	if (join.type != JoinType::INNER || join.ref_type != JoinRefType::REGULAR ||
	    join.right->type != TableReferenceType::BASE_TABLE || graph.where_clause) {
		return nullptr;
	}
	// DuckDB binds USING from its column list, without an ON expression.
	if (!join.using_columns.empty()) {
		return join.using_columns.size() == 1 ? DirectProperty(graph, alias, join.using_columns[0]) : nullptr;
	}
	if (!join.condition || alias.name.empty() ||
	    join.condition->GetExpressionType() != ExpressionType::COMPARE_EQUAL ||
	    join.condition->GetExpressionClass() != ExpressionClass::COMPARISON) {
		return nullptr;
	}
	const auto &on = join.condition->Cast<ComparisonExpression>();
	if (on.Left().GetExpressionClass() != ExpressionClass::COLUMN_REF ||
	    on.Right().GetExpressionClass() != ExpressionClass::COLUMN_REF) {
		return nullptr;
	}
	for (const auto *expr : {&on.Left(), &on.Right()}) {
		const auto &names = expr->Cast<ColumnRefExpression>().ColumnNames();
		if (names.size() == 2 && names[0] == alias.name) {
			return DirectProperty(graph, alias, names[1]);
		}
	}
	return nullptr;
}

unique_ptr<ParsedExpression> QwWatchlistPredicate(const SelectNode &graph, const TableAlias &graph_alias,
                                                  const JoinRef &join, idx_t max_keys) {
	if (join.type != JoinType::INNER || join.ref_type != JoinRefType::REGULAR || !join.condition ||
	    join.right->type != TableReferenceType::SUBQUERY || graph.where_clause || graph_alias.name.empty()) {
		return nullptr;
	}
	const auto &watch = join.right->Cast<SubqueryRef>();
	if (watch.alias.empty() || graph_alias.name == watch.alias || watch.column_name_alias.size() != 1 || watch.sample ||
	    watch.subquery->node->type != QueryNodeType::SELECT_NODE) {
		return nullptr;
	}
	const auto &values = watch.subquery->node->Cast<SelectNode>();
	if (!values.from_table || values.from_table->type != TableReferenceType::EXPRESSION_LIST ||
	    values.select_list.size() != 1 || !values.select_list[0]->Equals(StarExpression()) ||
	    !values.modifiers.empty() || values.where_clause || values.having || values.qualify) {
		return nullptr;
	}
	const auto &on = *join.condition;
	if (on.GetExpressionClass() != ExpressionClass::COMPARISON ||
	    on.GetExpressionType() != ExpressionType::COMPARE_EQUAL) {
		return nullptr;
	}
	const auto &comparison = on.Cast<ComparisonExpression>();
	if (comparison.Left().GetExpressionClass() != ExpressionClass::COLUMN_REF ||
	    comparison.Right().GetExpressionClass() != ExpressionClass::COLUMN_REF) {
		return nullptr;
	}
	auto graph_key = &comparison.Left().Cast<ColumnRefExpression>().ColumnNames();
	auto watch_key = &comparison.Right().Cast<ColumnRefExpression>().ColumnNames();
	if (graph_key->size() != 2 || watch_key->size() != 2) {
		return nullptr;
	}
	if ((*graph_key)[0] == watch.alias) {
		std::swap(graph_key, watch_key);
	}
	if ((*graph_key)[0] != graph_alias.name || (*watch_key)[0] != watch.alias ||
	    (*watch_key)[1] != watch.column_name_alias[0]) {
		return nullptr;
	}
	auto property = DirectProperty(graph, graph_alias, (*graph_key)[1]);
	if (!property) {
		return nullptr;
	}
	// ValuesClause is transformed by DuckDB itself into a SelectNode over ExpressionListRef.
	const auto &rows = values.from_table->Cast<ExpressionListRef>().values;
	if (rows.size() > max_keys) {
		return nullptr;
	}
	vector<unique_ptr<ParsedExpression>> args;
	args.push_back(property->Copy());
	for (const auto &row : rows) {
		if (row.size() != 1) {
			return nullptr;
		}
		bool negated = false;
		auto literal = IntegerOrNull(*row[0], negated);
		if (!literal) {
			return nullptr;
		}
		if (literal->IsNull()) {
			continue;
		}
		int64_t key;
		if (!literal->TryGetInt64(key) || (negated && key == NumericLimits<int64_t>::Minimum())) {
			return nullptr;
		}
		args.push_back(ConstantExpression::Integer(negated ? -key : key));
	}
	if (args.size() == 1) {
		return nullptr;
	}
	return make_uniq<OperatorExpression>(ExpressionType::COMPARE_IN, std::move(args));
}

namespace {
struct WatchlistPayload : FunctionData {
	explicit WatchlistPayload(Value query) : query(std::move(query)) {
	}
	Value query;
	unique_ptr<FunctionData> Copy() const override {
		return make_uniq<WatchlistPayload>(query);
	}
	bool Equals(const FunctionData &other) const override {
		return Value::NotDistinctFrom(query, other.Cast<WatchlistPayload>().query);
	}
};

// Unary '-' is an ordinary overloadable function in DuckDB. Use the binder
// that owns this query (including a stored view's search path), and also check
// the bound type of the same unqualified BIGINT cast used by the watchlist.
unique_ptr<FunctionData> BindWatchlistPayload(BindScalarFunctionInput &input) {
	bool eligible = false;
	if (input.HasBinder() && input.GetArguments()[2]->GetReturnType() == LogicalType::BIGINT) {
		auto entry = input.GetBinder().GetCatalogEntry(
		    EntryLookupInfo(CatalogType::SCALAR_FUNCTION_ENTRY, QualifiedName(Identifier("-"))),
		    OnEntryNotFound::RETURN_NULL);
		eligible = entry && entry->type == CatalogType::SCALAR_FUNCTION_ENTRY && entry->internal &&
		           entry->ParentCatalog().IsSystemCatalog();
	}
	return make_uniq<WatchlistPayload>(input.GetConstant(eligible ? 1 : 0));
}

unique_ptr<Expression> BoundWatchlistPayload(FunctionBindExpressionInput &input) {
	return make_uniq<BoundConstantExpression>(input.bind_data->Cast<WatchlistPayload>().query);
}
} // namespace

void QwRegisterWatchlistGuard(DatabaseInstance &db) {
	QwRegisterRuntimeWatchlist(db);
	ScalarFunction guard("qw_watchlist_payload", {LogicalType::VARCHAR, LogicalType::VARCHAR, LogicalType::ANY},
	                     LogicalType::VARCHAR, nullptr, BindWatchlistPayload);
	guard.SetBindExpressionCallback(BoundWatchlistPayload);
	ExtensionLoader(db, "quack_weave").RegisterFunction(std::move(guard));
}

unique_ptr<ParsedExpression> QwGuardWatchlistQuery(const string &base, const string &candidate) {
	vector<unique_ptr<ParsedExpression>> args;
	args.push_back(ConstantExpression::String(base));
	args.push_back(ConstantExpression::String(candidate));
	args.push_back(make_uniq<CastExpression>(LogicalType::BIGINT, ConstantExpression::Integer(0)));
	return make_uniq<FunctionExpression>(QualifiedName("system", "main", "qw_watchlist_payload"), std::move(args));
}
} // namespace duckdb
