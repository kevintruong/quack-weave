#include "c_api/lbug.h"
#include "cypher_lexer.h"
#include "parser/expression/parsed_literal_expression.h"
#include "parser/expression/parsed_property_expression.h"
#include "parser/expression/parsed_variable_expression.h"
#include "parser/parser.h"
#include "parser/query/reading_clause/match_clause.h"

#include <unordered_map>
#include "parser/query/regular_query.h"

namespace {

using lbug::common::ClauseType;

template <typename Query>
bool has_only_graph_clauses(const Query& query) {
    if (query.getNumUpdatingClauses() != 0) {
        return false;
    }
    for (uint32_t index = 0; index < query.getNumReadingClauses(); ++index) {
        const auto type = query.getReadingClause(index)->getClauseType();
        if (type != ClauseType::MATCH && type != ClauseType::UNWIND) {
            return false;
        }
    }
    return true;
}

} // namespace

extern "C" lbug_state qw_ladybug_open_database(const char* path, bool read_only,
    lbug_database* database) noexcept {
    try {
        auto config = lbug_default_system_config();
        config.read_only = read_only;
        return lbug_database_init(path, config, database);
    } catch (...) {
        return LbugError;
    }
}

extern "C" bool qw_ladybug_is_graph_read(const char* text) noexcept {
    try {
        const auto statements = lbug::parser::Parser::parseQuery(text);
        if (statements.size() != 1 ||
            statements.front()->getStatementType() != lbug::common::StatementType::QUERY) {
            return false;
        }

        const auto& query = static_cast<const lbug::parser::RegularQuery&>(*statements.front());
        for (lbug::common::idx_t index = 0; index < query.getNumSingleQueries(); ++index) {
            const auto& part = *query.getSingleQuery(index);
            if (!part.hasReturnClause() || !has_only_graph_clauses(part)) {
                return false;
            }
            for (uint32_t part_index = 0; part_index < part.getNumQueryParts(); ++part_index) {
                if (!has_only_graph_clauses(*part.getQueryPart(part_index))) {
                    return false;
                }
            }
        }
        return query.getNumSingleQueries() != 0;
    } catch (...) {
        return false;
    }
}

using projection_field = bool (*)(void*, const char*, const char*, const char*);
extern "C" bool qw_ladybug_project(const char* text, projection_field visit, void* output) noexcept {
    using namespace lbug::parser;
    using lbug::common::ExpressionType;
    try {
        const auto statements = Parser::parseQuery(text);
        if (statements.size() != 1 ||
            statements.front()->getStatementType() != lbug::common::StatementType::QUERY) {
            return false;
        }
        const auto& query = static_cast<const RegularQuery&>(*statements.front());
        if (query.getNumSingleQueries() != 1) return false;
        const auto& single = *query.getSingleQuery(0);
        if (single.getNumQueryParts() || !single.hasReturnClause() ||
            single.getNumUpdatingClauses() || !single.getNumReadingClauses()) return false;

        // Only infer properties whose source label is unambiguous in this projection scope.
        std::unordered_map<std::string, std::string> labels;
        auto record = [&](const NodePattern& element) {
            const auto variable = element.getVariableName();
            const auto types = element.getTableNames();
            if (variable.empty() || types.empty()) return;
            auto [it, inserted] = labels.emplace(variable, types.front());
            if (types.size() != 1 || (!inserted && it->second != types.front())) it->second.clear();
        };
        for (uint32_t i = 0; i < single.getNumReadingClauses(); ++i) {
            const auto* clause = single.getReadingClause(i);
            if (clause->getClauseType() != ClauseType::MATCH) return false;
            for (const auto& path : static_cast<const MatchClause*>(clause)->getPatternElementsRef()) {
                record(*path.getFirstNodePattern());
                for (uint32_t j = 0; j < path.getNumPatternElementChains(); ++j) {
                    const auto& edge = *path.getPatternElementChain(j);
                    record(*edge.getRelPattern());
                    record(*edge.getNodePattern());
                }
            }
        }
        const auto& body = *single.getReturnClause()->getProjectionBody();
        if (body.getProjectionExpressions().empty()) return false;
        for (const auto& expr : body.getProjectionExpressions()) {
            if (expr->getExpressionType() == ExpressionType::LITERAL) {
                const auto literal = expr->constCast<ParsedLiteralExpression>().getValue();
                const auto type = literal.getDataType().toString();
                const auto name = expr->hasAlias() ? expr->getAlias() : expr->getRawName();
                if (!visit(output, "", type.c_str(), name.c_str())) return false;
                continue;
            }
            if (expr->getExpressionType() != ExpressionType::PROPERTY || expr->getNumChildren() != 1 ||
                expr->getChild(0)->getExpressionType() != ExpressionType::VARIABLE) return false;
            const auto& property = expr->constCast<ParsedPropertyExpression>();
            const auto variable = expr->getChild(0)->constCast<ParsedVariableExpression>().getVariableName();
            const auto label = labels.find(variable);
            if (label == labels.end() || label->second.empty() || property.isStar()) return false;
            const auto name = expr->hasAlias() ? expr->getAlias() : variable + "." + property.getPropertyName();
            if (!visit(output, label->second.c_str(), property.getPropertyName().c_str(), name.c_str())) {
                return false;
            }
        }
        return true;
    } catch (...) {
        return false;
    }
}

// The ordinary string binding takes a C string. Length-delimited strings preserve embedded NULs.
extern "C" lbug_state qw_ladybug_bind_text(lbug_prepared_statement* statement, const char* name,
    const char* bytes, size_t size) noexcept {
    try {
        auto value = bytes ? lbug::common::Value(std::string(bytes, size))
                           : lbug::common::Value::createNullValue();
        lbug_value handle{&value, true};
        return lbug_prepared_statement_bind_value(statement, name, &handle);
    } catch (...) {
        return LbugError;
    }
}

// Use the provider's tokens so a dollar inside a literal, identifier or comment
// cannot become a DuckDB parameter. The generated Cypher lexer splits $ and name.
extern "C" bool qw_cypher_parameters(const char* text, size_t length,
    bool (*visit)(void*, const char*, size_t), void* output) noexcept {
    try {
        antlr4::ANTLRInputStream stream(text, length);
        CypherLexer lexer(&stream);
        lexer.removeErrorListeners();
        for (auto token = lexer.nextToken(); token->getType() != antlr4::Token::EOF; token = lexer.nextToken()) {
            if (token->getText() != "$") continue;
            auto name = lexer.nextToken()->getText();
            if (!visit(output, name.data(), name.size())) return false;
        }
        return true;
    } catch (...) {
        return false;
    }
}
