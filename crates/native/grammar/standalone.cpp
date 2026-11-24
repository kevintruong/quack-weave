#include "graph_table.hpp"

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

using ParameterVisitor = bool (*)(void *, const char *, size_t);
extern "C" bool qw_gql_parameters(const char *, size_t, ParameterVisitor, void *) noexcept;
extern "C" bool qw_cypher_parameters(const char *, size_t, ParameterVisitor, void *) noexcept;

namespace duckdb {
namespace {

constexpr const char *GRAMMAR = "quack_weave";

unique_ptr<ParsedExpression> CurrentOption(const char *option) {
	vector<unique_ptr<ParsedExpression>> args;
	args.push_back(ConstantExpression::String(option));
	return make_uniq<FunctionExpression>(QualifiedName("system", "main", "current_setting"), std::move(args));
}

bool CollectParameter(void *output, const char *bytes, size_t length) {
	auto &names = *static_cast<vector<string> *>(output);
	string name(bytes, length);
	if (name.empty() || !(StringUtil::CharacterIsAlpha(name[0]) || name[0] == '_')) return false;
	for (auto c : name) {
		if (!(StringUtil::CharacterIsAlpha(c) || StringUtil::CharacterIsDigit(c) || c == '_')) return false;
	}
	for (const auto &previous : names) {
		if (previous == name) return true;
		if (StringUtil::CIEquals(previous, name)) return false;
	}
	names.push_back(std::move(name));
	return true;
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
	auto source = text->substr(span.offset, span.length);
	args.push_back(ConstantExpression::String(source));

	vector<string> names;
	if (source.find('$') != string::npos) {
		string dialect = "gql";
		if (transformer.options.context) {
			transformer.options.context->TryGetCurrentSetting(Identifier("qw_graph_dialect"), dialect);
		}
		auto enumerate = dialect == "cypher" ? qw_cypher_parameters : qw_gql_parameters;
		if (!enumerate(source.data(), source.size(), CollectParameter, &names)) {
			throw ParserException("QW_ARGUMENT: Expected distinct ASCII graph parameter names");
		}
	}
	if (!names.empty()) {
		vector<unique_ptr<ParsedExpression>> fields;
		for (const auto &name : names) {
			auto field = PEGTransformerFactory::TransformColLabelParameter(transformer, name);
			field->SetAlias(Identifier(name));
			fields.push_back(std::move(field));
		}
		args.push_back(make_uniq<FunctionExpression>(QualifiedName("system", "main", "struct_pack"), std::move(fields)));
	}

	auto read = make_uniq<TableFunctionRef>();
	read->function = make_uniq<FunctionExpression>(QualifiedName("system", "main", names.empty() ? "qw_graph_query" : "qw_graph_query_params"), std::move(args));
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
		QwAddGraphTableRules(changes);
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
