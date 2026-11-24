#include "graph_table.hpp"
#include "watchlist.hpp"
#include "duckdb/parser/expression/comparison_expression.hpp"
#include "duckdb/parser/expression/operator_expression.hpp"

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

// Provider identifiers are restricted to simple tokens.
string ProviderName(const Identifier &identifier) {
	const auto &name = identifier.GetIdentifierName();
	auto letter = [](char c) {
		return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_';
	};
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

// Reuse the original DuckDB WHERE as a residual for every provider prefilter.
constexpr idx_t MAX_PREFILTER_KEYS = 64;

struct Candidate {
	string label, property, predicate;
};

struct GraphBindings {
	identifier_map_t<string> labels;
	identifier_map_t<Identifier> variables;
	identifier_map_t<identifier_map_t<Identifier>> properties;
	vector<string> projections;

	string Element(PEGTransformer &transformer, ParseResult &element, bool edge) {
		auto &list = element.Cast<ListParseResult>();
		auto variable = transformer.Transform<Identifier>(list, 1);
		auto label = transformer.Transform<Identifier>(list, 3);
		auto inserted = variables.emplace(variable, variable);
		auto canonical = inserted.first->second;
		labels[canonical] = inserted.second ? ProviderName(label) : "";
		auto binding = ProviderName(canonical) + ":" + ProviderName(label);
		return edge ? "[" + binding + "]" : "(" + binding + ")";
	}

	Candidate Prefilter(const ParsedExpression &expr) const {
		const ParsedExpression *property = nullptr;
		vector<const ParsedExpression *> values;
		bool equality = expr.GetExpressionType() == ExpressionType::COMPARE_EQUAL;
		if (equality && expr.GetExpressionClass() == ExpressionClass::COMPARISON) {
			const auto &cmp = expr.Cast<ComparisonExpression>();
			property = &cmp.Left();
			values.push_back(&cmp.Right());
		} else if (expr.GetExpressionType() == ExpressionType::COMPARE_IN &&
		           expr.GetExpressionClass() == ExpressionClass::OPERATOR) {
			const auto &args = expr.Cast<OperatorExpression>().GetChildren();
			if (args.size() < 2 || args.size() - 1 > MAX_PREFILTER_KEYS)
				return {};
			property = args[0].get();
			for (idx_t i = 1; i < args.size(); ++i)
				values.push_back(args[i].get());
		} else {
			return {};
		}
		if (property->GetExpressionClass() != ExpressionClass::COLUMN_REF)
			return {};
		const auto &names = property->Cast<ColumnRefExpression>().ColumnNames();
		if (names.size() != 2)
			return {};
		const auto variable = variables.find(names[0]);
		const auto label = labels.find(names[0]);
		if (variable == variables.end() || label == labels.end() || label->second.empty())
			return {};
		vector<string> literals;
		for (const auto *value : values) {
			if (value->GetExpressionClass() != ExpressionClass::CONSTANT)
				return {};
			int64_t n;
			if (!value->Cast<ConstantExpression>().GetLiteral().TryGetInt64(n))
				return {};
			literals.push_back(std::to_string(n));
		}
		const auto name = ProviderName(names[1]);
		const auto lhs = ProviderName(variable->second) + "." + name;
		return {label->second, name,
		        equality ? lhs + " = " + literals[0] : lhs + " IN [" + StringUtil::Join(literals, ", ") + "]"};
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

// Keep the graph's parsed projections until DuckDB has transformed the join
// suffix. This preserves source-order parameter binding in both subtrees.
struct ParsedGraphTable {
	Identifier graph;
	GraphBindings bindings;
	string query;
	unique_ptr<SelectNode> result;
	TableAlias table_alias;

	ParsedGraphTable(PEGTransformer &transformer, ParseResult &parse_result);
	unique_ptr<TableRef> Lower(const JoinRef *join);
};

ParsedGraphTable::ParsedGraphTable(PEGTransformer &transformer, ParseResult &parse_result) {
	auto &rule = parse_result.Cast<ListParseResult>();
	graph = transformer.Transform<Identifier>(rule, 2);
	query = "MATCH " + bindings.Element(transformer, rule.GetChild(4), false);
	auto &steps = rule.Child<OptionalParseResult>(5);
	if (steps.HasResult()) {
		for (auto &step : steps.GetResult().Cast<RepeatParseResult>().GetChildren()) {
			auto &parts = step.get().Cast<ListParseResult>();
			query += "-" + bindings.Element(transformer, parts.GetChild(1), true) + "->" +
			         bindings.Element(transformer, parts.GetChild(3), false);
		}
	}

	result = make_uniq<SelectNode>();
	result->aggregate_handling = AggregateHandling::NO_AGGREGATES_ALLOWED;
	transformer.TransformOptional(rule, 6, result->where_clause);
	result->select_list = transformer.Transform<vector<unique_ptr<ParsedExpression>>>(rule, 9);
	auto &alias = rule.Child<OptionalParseResult>(12);
	if (alias.HasResult()) {
		table_alias = transformer.Transform<TableAlias>(alias.GetResult());
	}
}

unique_ptr<TableRef> ParsedGraphTable::Lower(const JoinRef *join) {
	Candidate candidate;
	const ParsedExpression *watch_key = nullptr;
	string watch_variable, watch_property, watch_label;
	if (result->where_clause) {
		candidate = bindings.Prefilter(*result->where_clause);
	} else if (join) {
		auto predicate = QwWatchlistPredicate(*result, table_alias, *join, MAX_PREFILTER_KEYS);
		if (predicate) {
			candidate = bindings.Prefilter(*predicate);
		} else if ((watch_key = QwTableWatchKey(*result, table_alias, *join))) {
			const auto &names = watch_key->Cast<ColumnRefExpression>().ColumnNames();
			if (names.size() == 2 && bindings.variables.count(names[0]) && !bindings.labels.at(names[0]).empty()) {
				watch_variable = ProviderName(bindings.variables.at(names[0]));
				watch_property = ProviderName(names[1]);
				watch_label = bindings.labels.at(names[0]);
			}
		}
	}
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
	const auto projection = " RETURN " + (bindings.projections.empty() ? string("1 AS qw_row")
	                                                                   : StringUtil::Join(bindings.projections, ", "));

	vector<unique_ptr<ParsedExpression>> args;
	args.push_back(ConstantExpression::String(graph.GetIdentifierName()));
	args.push_back(ConstantExpression::String("cypher"));
	args.push_back(ConstantExpression::String(query + projection));
	const char *function = "qw_graph_query";
	if (!watch_label.empty()) {
		function = "qw_graph_query_watch";
		args.push_back(ConstantExpression::String(watch_label));
		args.push_back(ConstantExpression::String(watch_property));
		args.push_back(ConstantExpression::String(watch_variable));
		args.push_back(ConstantExpression::String(watch_key->Cast<ColumnRefExpression>().ColumnNames()[0].GetIdentifierName()));
	} else if (!candidate.predicate.empty()) {
		function = "qw_graph_query_filtered";
		args.push_back(ConstantExpression::String(candidate.label));
		args.push_back(ConstantExpression::String(candidate.property));
		auto filtered = query + " WHERE " + candidate.predicate + projection;
		args.push_back(join && !result->where_clause ? QwGuardWatchlistQuery(query + projection, filtered)
		                                             : ConstantExpression::String(std::move(filtered)));
	}
	auto scan = make_uniq<TableFunctionRef>();
	scan->function = make_uniq<FunctionExpression>(QualifiedName("system", "main", function), std::move(args));
	result->from_table = std::move(scan);
	auto statement = make_uniq<SelectStatement>();
	statement->node = std::move(result);
	auto ref = make_uniq<SubqueryRef>(std::move(statement));
	ref->alias = std::move(table_alias.name);
	ref->column_name_alias = std::move(table_alias.column_name_alias);
	return std::move(ref);
}

arena_ptr<TransformResultValue> TransformGraphTable(PEGTransformer &transformer, ParseResult &parse_result) {
	return transformer.MakeResult<unique_ptr<TableRef>>(ParsedGraphTable(transformer, parse_result).Lower(nullptr));
}

ParseResult *LeadingGraph(ParseResult &node) {
	auto child = &node;
	bool is_graph = false;
	while (true) {
		is_graph = is_graph || child->Name() == "QwGraphTable";
		if (child->type == ParseResultType::CHOICE) {
			child = &child->Cast<ChoiceParseResult>().GetResult();
		} else if (child->type == ParseResultType::LIST && child->Cast<ListParseResult>().GetChildren().size() == 1) {
			child = &child->Cast<ListParseResult>().GetChild(0);
		} else {
			return is_graph && child->type == ParseResultType::LIST ? child : nullptr;
		}
	}
}

// Schedule the ordinary join and pivot subtrees on DuckDB's transform stack.
// Recursing through nested joins here would bypass DuckDB's trampoline.
class JoinedGraphProcess final : public TransformProcess {
public:
	JoinedGraphProcess(PEGTransformer &transformer, ParseResult &graph, RepeatParseResult &joins)
	    : transformer(transformer), graph(transformer, graph), joins(joins) {
	}
	TransformStep Resume(arena_ptr<TransformResultValue> child) override {
		if (child) {
			auto value = TryGetTransformResult<unique_ptr<TableRef>>(*child);
			if (!value) {
				throw InternalException("Expected a join or pivot table reference");
			}
			suffixes.push_back(std::move(*value));
		}
		const auto entries = joins.GetChildren();
		if (suffixes.size() < entries.size()) {
			return TransformStep::Child({entries[suffixes.size()].get()});
		}
		const auto &first = *suffixes[0];
		auto left = graph.Lower(first.type == TableReferenceType::JOIN ? &first.Cast<JoinRef>() : nullptr);
		return TransformStep::Complete(transformer.MakeResult<unique_ptr<TableRef>>(
		    PEGTransformerFactory::TransformJoinedTableRefChain(transformer, std::move(left), std::move(suffixes))));
	}

private:
	PEGTransformer &transformer;
	ParsedGraphTable graph;
	RepeatParseResult &joins;
	vector<unique_ptr<TableRef>> suffixes;
};

arena_ptr<TransformProcess> StartTableChain(PEGTransformer &transformer, ParseResult &parse_result,
                                            const TransformFrameOps &native) {
	auto &list = parse_result.Cast<ListParseResult>();
	auto &joins = list.GetChild(1);
	if (joins.type != ParseResultType::OPTIONAL || joins.Cast<OptionalParseResult>().HasResult()) {
		if (auto graph = LeadingGraph(list.GetChild(0))) {
			auto &repeat =
			    joins.type == ParseResultType::OPTIONAL ? joins.Cast<OptionalParseResult>().GetResult() : joins;
			return transformer.MakeProcess<JoinedGraphProcess>(transformer, *graph, repeat.Cast<RepeatParseResult>());
		}
	}
	return transformer.MakeProcess<GeneratedTransformProcess>(transformer, TransformInput {parse_result}, native);
}

arena_ptr<TransformProcess> StartGraphTable(PEGTransformer &transformer, ParseResult &parse_result) {
	return transformer.MakeProcess<FinalizeTransformProcess>(transformer, parse_result, TransformGraphTable);
}

} // namespace

void QwAddGraphTableRules(vector<GrammarChange> &changes) {
	changes.push_back(GrammarChange::AddRule(
	    "QwGraphTable <- 'GRAPH_TABLE' '(' Identifier 'MATCH' QwPgqVertex QwPgqStep* WhereClause? "
	    "'COLUMNS' '(' TargetList ')' ')' TableAlias?",
	    StartGraphTable));
	changes.push_back(GrammarChange::AddRule("QwPgqVertex <- '(' Identifier ':' Identifier ')'"));
	changes.push_back(GrammarChange::AddRule("QwPgqEdge <- '[' Identifier ':' Identifier ']'"));
	changes.push_back(GrammarChange::AddRule("QwPgqStep <- '-' QwPgqEdge '->' QwPgqVertex"));
	changes.push_back(GrammarChange::PrependChoice("InnerTableRef", "QwGraphTable"));
	// Inspect joins only at their native chain boundary. InnerTableRef can also
	// appear to the right of CROSS JOIN, where consuming a suffix would regroup SQL.
	for (const string rule : {"TableRef", "JoinedTableRefChain"}) {
		const auto native = PEGTransformerFactory::GeneratedTransformFrameOps().at(rule);
		changes.push_back(GrammarChange::SetTransformProcess(
		    rule, [native](PEGTransformer &t, ParseResult &r) { return StartTableChain(t, r, *native); },
		    rule == "TableRef"));
	}
}

} // namespace duckdb
