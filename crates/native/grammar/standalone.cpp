
#include "duckdb/main/capi_v2/capi_v2_internal.hpp"
#include "duckdb/main/client_config.hpp"
#include "duckdb/main/settings.hpp"
#include "duckdb/parser/expression/function_expression.hpp"
#include "duckdb/parser/expression/star_expression.hpp"
#include "duckdb/parser/grammar_extension.hpp"
#include "duckdb/parser/peg/passthrough_dialect.hpp"
#include "duckdb/parser/peg/transformer/peg_transformer.hpp"
#include "duckdb/parser/tableref/table_function_ref.hpp"
#include "duckdb/planner/extension_callback.hpp"

namespace duckdb {
namespace {

constexpr const char *GRAMMAR = "quack_weave";

unique_ptr<ParsedExpression> CurrentOption(const char *option) {
	vector<unique_ptr<ParsedExpression>> args;
	args.push_back(ConstantExpression::String(option));
	return make_uniq<FunctionExpression>(QualifiedName("system", "main", "current_setting"), std::move(args));
}

arena_ptr<TransformResultValue> TransformMatch(PEGTransformer &transformer, ParseResult &result) {
	auto text = transformer.token_iterator.Source();
	auto span = result.GetLocation();
	if (!text || !span.IsValid()) {
		throw ParserException("Unable to retrieve the source of the graph statement");
	}
	// Pass the original source span as a value. Identifiers, comments and literals
	// belong to the selected graph parser, and never become SQL expressions.
	vector<unique_ptr<ParsedExpression>> args;
	args.push_back(CurrentOption("qw_selected_graph"));
	args.push_back(CurrentOption("qw_graph_dialect"));
	args.push_back(ConstantExpression::String(text->substr(span.offset, span.length)));

	auto read = make_uniq<TableFunctionRef>();
	read->function = make_uniq<FunctionExpression>(QualifiedName("system", "main", "qw_graph_query"), std::move(args));
	auto select = make_uniq<SelectNode>();
	select->from_table = std::move(read);
	select->select_list.push_back(make_uniq<StarExpression>());
	auto statement = make_uniq<SelectStatement>();
	statement->node = std::move(select);
	return transformer.MakeResult<unique_ptr<SQLStatement>>(std::move(statement));
}

arena_ptr<TransformResultValue> TransformSelection(PEGTransformer &transformer, ParseResult &result) {
	auto graph = transformer.Transform<Identifier>(result.Cast<ListParseResult>(), 4);
	auto value = ConstantExpression::String(graph.GetIdentifierName());
	return transformer.MakeResult<unique_ptr<SQLStatement>>(
	    make_uniq<SetVariableStatement>("qw_selected_graph", std::move(value), SetScope::SESSION));
}

class GraphGrammar final : public GrammarExtension {
public:
	GraphGrammar() : GrammarExtension(GRAMMAR, "Read a selected Ladybug graph") {
	}

	vector<GrammarChange> GetChanges() const override {
		vector<GrammarChange> changes;
		changes.push_back(GrammarChange::AddRule("QwGraphToken <- Identifier"));
		changes.push_back(GrammarChange::AddTerminalRuleOverride("QwGraphToken", [](const PEGKeywordHelper &) {
			return make_uniq<PassthroughTokenMatcher>();
		}));
		changes.push_back(GrammarChange::AddRule("QwStandalone <- 'MATCH' QwGraphToken+", [](PEGTransformer &t, ParseResult &r) {
			return t.MakeProcess<FinalizeTransformProcess>(t, r, TransformMatch);
		}));
		changes.push_back(GrammarChange::AddRule("QwSelectGraph <- 'SESSION' 'SET' 'PROPERTY'? 'GRAPH' Identifier",
		                                         [](PEGTransformer &t, ParseResult &r) {
			return t.MakeProcess<FinalizeTransformProcess>(t, r, TransformSelection);
		}));
		changes.push_back(GrammarChange::PrependChoice("Statement", "QwStandalone"));
		changes.push_back(GrammarChange::PrependChoice("Statement", "QwSelectGraph"));
		return changes;
	}
};

void Activate(ClientContext &context) {
	vector<Value> names;
	for (const auto &name : ClientConfig::GetConfig(context).active_grammar_extensions) {
		if (StringUtil::CIEquals(name, GRAMMAR)) {
			return;
		}
		names.emplace_back(name);
	}
	names.emplace_back(GRAMMAR);
	ActiveGrammarExtensionsSetting::SetLocal(context, Value::LIST(LogicalType::VARCHAR, std::move(names)));
}

class GraphConnections final : public ExtensionCallback {
public:
	void OnConnectionOpened(ClientContext &context) override {
		Activate(context);
	}
};

} // namespace
} // namespace duckdb

// Both handles and all C++ types here belong to the exact pinned DuckDB ABI.
// Rust copies the diagnostic immediately; exceptions never cross the FFI call.
extern "C" const char *qw_register_graph_grammar(duckdb_v2_factory_handle handle) noexcept {
	try {
		auto &factory = *duckdb::capiv2::Convert(handle);
		auto &db = factory.GetDatabase();
		auto context = factory.TryGetClientContext();
		if (!context) {
			throw duckdb::InternalException("Graph grammar registration requires the loading connection");
		}
		duckdb::GrammarExtension::Register(db, duckdb::make_shared_ptr<duckdb::GraphGrammar>());
		duckdb::Activate(*context);
		duckdb::ExtensionCallbackManager::Get(db).Register(duckdb::make_shared_ptr<duckdb::GraphConnections>());
		return nullptr;
	} catch (const std::exception &error) {
		static thread_local std::string message;
		message = error.what();
		return message.c_str();
	} catch (...) {
		return "Unexpected failure registering the DuckDB graph grammar";
	}
}
