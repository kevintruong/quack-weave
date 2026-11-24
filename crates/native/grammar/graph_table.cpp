#include "graph_table.hpp"

#include "duckdb/parser/expression/columnref_expression.hpp"
#include "duckdb/parser/expression/constant_expression.hpp"
#include "duckdb/parser/expression/function_expression.hpp"
#include "duckdb/parser/peg/ast/table_alias.hpp"
#include "duckdb/parser/peg/transformer/peg_transformer.hpp"
#include "duckdb/parser/query_node/select_node.hpp"
#include "duckdb/parser/tableref/subqueryref.hpp"
#include "duckdb/parser/tableref/table_function_ref.hpp"

namespace duckdb {
namespace {

// Only identifier tokens cross into the generated provider statement. All SQL
// expressions and literal values stay in their original DuckDB expression tree.
string ProviderName(const Identifier &identifier) {
	const auto &name = identifier.GetIdentifierName();
	auto letter = [](char c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_'; };
	if (name.empty() || !letter(name[0])) {
		throw NotImplementedException("GRAPH_TABLE requires simple graph identifiers");
	}
	for (const auto c : name) {
		if (!letter(c) && !(c >= '0' && c <= '9')) {
			throw NotImplementedException("GRAPH_TABLE requires simple graph identifiers");
		}
	}
	return name;
}

struct GraphBindings {
	identifier_map_t<Identifier> variables;
	identifier_map_t<identifier_map_t<Identifier>> properties;
	vector<string> projections;

	string Element(PEGTransformer &transformer, ParseResult &element, bool edge) {
		auto &list = element.Cast<ListParseResult>();
		auto variable = transformer.Transform<Identifier>(list, 1);
		auto label = transformer.Transform<Identifier>(list, 3);
		auto canonical = variables.emplace(variable, variable).first->second;
		auto binding = ProviderName(canonical) + ":" + ProviderName(label);
		return edge ? "[" + binding + "]" : "(" + binding + ")";
	}

	void BindProperties(ParsedExpression &expression) {
		auto kind = expression.GetExpressionClass();
		if (kind == ExpressionClass::SUBQUERY || kind == ExpressionClass::STAR || kind == ExpressionClass::WINDOW ||
		    (kind == ExpressionClass::FUNCTION && expression.Cast<FunctionExpression>().FunctionName() == "unnest")) {
			throw NotImplementedException("GRAPH_TABLE requires scalar expressions over named graph properties");
		}
		if (expression.GetExpressionClass() != ExpressionClass::COLUMN_REF) {
			for (auto &child : expression.ChildrenMutable()) {
				BindProperties(*child);
			}
			return;
		}
		auto &names = expression.Cast<ColumnRefExpression>().ColumnNamesMutable();
		if (names.size() != 2) {
			throw BinderException("GRAPH_TABLE expects a graph property reference of the form variable.property");
		}
		auto variable = variables.find(names[0]);
		if (variable == variables.end()) {
			throw BinderException("Unknown GRAPH_TABLE pattern variable %s", names[0]);
		}
		auto &bound = properties[variable->second];
		auto entry = bound.find(names[1]);
		if (entry == bound.end()) {
			auto alias = Identifier("qw_col" + std::to_string(projections.size()));
			auto property = ProviderName(variable->second) + "." + ProviderName(names[1]);
			projections.push_back(property + " AS " + alias.GetIdentifierName());
			entry = bound.emplace(names[1], std::move(alias)).first;
		}
		names = {entry->second};
	}
};

arena_ptr<TransformResultValue> TransformGraphTable(PEGTransformer &transformer, ParseResult &parse_result) {
	auto &rule = parse_result.Cast<ListParseResult>();
	auto graph = transformer.Transform<Identifier>(rule, 2);
	GraphBindings bindings;
	string query = "MATCH " + bindings.Element(transformer, rule.GetChild(4), false);
	auto &steps = rule.Child<OptionalParseResult>(5);
	if (steps.HasResult()) {
		for (auto &step : steps.GetResult().Cast<RepeatParseResult>().GetChildren()) {
			auto &parts = step.get().Cast<ListParseResult>();
			query += "-" + bindings.Element(transformer, parts.GetChild(1), true) + "->" +
			         bindings.Element(transformer, parts.GetChild(3), false);
		}
	}

	auto result = make_uniq<SelectNode>();
	result->aggregate_handling = AggregateHandling::NO_AGGREGATES_ALLOWED;
	transformer.TransformOptional(rule, 6, result->where_clause);
	result->select_list = transformer.Transform<vector<unique_ptr<ParsedExpression>>>(rule, 9);
	for (auto &expression : result->select_list) {
		// The provider's private projection names must never become SQL output names.
		if (!expression->HasAlias()) {
			expression->SetAlias(expression->GetName());
		}
		bindings.BindProperties(*expression);
	}
	if (result->where_clause) {
		bindings.BindProperties(*result->where_clause);
	}
	// A constant projection still returns one row per pattern match.
	query += " RETURN " + (bindings.projections.empty() ? string("1 AS qw_row") :
	                      StringUtil::Join(bindings.projections, ", "));

	vector<unique_ptr<ParsedExpression>> args;
	args.push_back(ConstantExpression::String(graph.GetIdentifierName()));
	args.push_back(ConstantExpression::String("cypher"));
	args.push_back(ConstantExpression::String(std::move(query)));
	auto scan = make_uniq<TableFunctionRef>();
	scan->function = make_uniq<FunctionExpression>(QualifiedName("system", "main", "qw_graph_query"), std::move(args));
	result->from_table = std::move(scan);
	auto statement = make_uniq<SelectStatement>();
	statement->node = std::move(result);
	auto ref = make_uniq<SubqueryRef>(std::move(statement));
	auto &alias = rule.Child<OptionalParseResult>(12);
	if (alias.HasResult()) {
		auto table_alias = transformer.Transform<TableAlias>(alias.GetResult());
		ref->alias = std::move(table_alias.name);
		ref->column_name_alias = std::move(table_alias.column_name_alias);
	}
	return transformer.MakeResult<unique_ptr<TableRef>>(std::move(ref));
}

arena_ptr<TransformProcess> StartGraphTable(PEGTransformer &transformer, ParseResult &parse_result) {
	return transformer.MakeProcess<FinalizeTransformProcess>(transformer, parse_result, TransformGraphTable);
}

} // namespace

void QwAddGraphTableRules(vector<GrammarChange> &changes) {
	changes.push_back(GrammarChange::AddRule(
	    "QwGraphTable <- 'GRAPH_TABLE' '(' Identifier 'MATCH' QwPgqVertex QwPgqStep* WhereClause? "
	    "'COLUMNS' '(' TargetList ')' ')' TableAlias?", StartGraphTable));
	changes.push_back(GrammarChange::AddRule("QwPgqVertex <- '(' Identifier ':' Identifier ')'"));
	changes.push_back(GrammarChange::AddRule("QwPgqEdge <- '[' Identifier ':' Identifier ']'"));
	changes.push_back(GrammarChange::AddRule("QwPgqStep <- '-' QwPgqEdge '->' QwPgqVertex"));
	changes.push_back(GrammarChange::PrependChoice("InnerTableRef", "QwGraphTable"));
}

} // namespace duckdb
