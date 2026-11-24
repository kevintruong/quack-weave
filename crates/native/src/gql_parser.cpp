#include "GQLLexer.h"
#include "GQLParser.h"
#include "antlr4-runtime.h"

#include <cstdint>
#include <memory>
#include <string_view>
#include <vector>

namespace {

enum Status : std::int32_t {
    success = 0,
    syntax = 1,
    unsupported = 2,
    limit = 3,
    internal = 4,
};

enum Comparison : std::int32_t { eq, ne, lt, le, gt, ge };
enum Literal : std::int32_t { boolean, integer, negative_integer, string, parameter };
enum PredicateStyle : std::int32_t { absent, where, filter };

struct Diagnostic {
    std::int32_t status;
    std::size_t line;
    std::size_t column;
};

struct Span {
    // ANTLR indexes the UTF-32 code points of its decoded input.
    std::size_t begin;
    std::size_t end;
    std::size_t line;
    std::size_t column;
};

struct Node {
    Span variable;
    Span label;
};

struct Property {
    Span variable;
    Span name;
};

struct Projection {
    Property property;
    Span alias;
};

struct Predicate {
    std::int32_t style;
    std::int32_t comparison;
    std::int32_t literal_kind;
    Property property;
    Span literal_text;
};

struct SortKey {
    Span alias;
    bool descending;
};

struct ReadView {
    Node left;
    Span relationship_label;
    Node right;
    Predicate predicate;
    const Projection *projections;
    std::size_t projection_count;
    Span relationship_variable;
    bool distinct;
    Span limit;
    const SortKey *sort_keys;
    std::size_t sort_count;
};

struct ParsedRead {
    ReadView view{};
    std::vector<Projection> projections;
    std::vector<SortKey> sort_keys;
};

constexpr std::size_t max_input_bytes = 16 * 1024;
constexpr std::size_t max_lexer_tokens = 256;
constexpr std::size_t max_delimiter_depth = 16;

using Context = antlr4::ParserRuleContext;
using Token = antlr4::Token;

Diagnostic at(Status status, const Token *token) {
    return token ? Diagnostic{status, token->getLine(), token->getCharPositionInLine()}
                 : Diagnostic{status, 0, 0};
}

struct Errors final : antlr4::BaseErrorListener {
    Diagnostic first{};

    void syntaxError(antlr4::Recognizer *, Token *, std::size_t line, std::size_t column,
            const std::string &, std::exception_ptr) override {
        if (!first.status) {
            first = {syntax, line, column};
        }
    }
};

[[noreturn]] void reject(Context &context) {
    throw at(unsupported, context.getStart());
}

void deny(Context *context) {
    if (context) {
        reject(*context);
    }
}

template <class T> T &require(T *child, Context &owner) {
    if (!child) {
        reject(owner);
    }
    return *child;
}

Span span(const Token &start, const Token &stop) {
    return {start.getStartIndex(), stop.getStopIndex() + 1,
        start.getLine(), start.getCharPositionInLine()};
}

Span span(Context &context) {
    return span(*context.getStart(), *context.getStop());
}

Span label(GQLParser::ElementPatternFillerContext &filler) {
    deny(filler.elementPatternPredicate());
    auto &is_label = require(filler.isLabelExpression(), filler);
    auto &name = require(
        dynamic_cast<GQLParser::LabelExpressionNameContext *>(is_label.labelExpression()), is_label);
    return span(*name.labelName());
}

Node node(GQLParser::ElementPatternContext &element) {
    auto &node = require(element.nodePattern(), element);
    auto &filler = *node.elementPatternFiller();
    auto &variable = require(filler.elementVariableDeclaration(), filler);
    return {span(variable), label(filler)};
}

Span relationship(GQLParser::ElementPatternContext &element, bool native, ReadView &read) {
    auto &edge = require(element.edgePattern(), element);
    auto &full = require(edge.fullEdgePattern(), edge);
    auto &right = require(full.fullEdgePointingRight(), full);
    auto &filler = *right.elementPatternFiller();
    if (auto *variable = filler.elementVariableDeclaration()) {
        if (!native) reject(*variable);
        read.relationship_variable = span(*variable);
    }
    return label(filler);
}

GQLParser::ElementPatternContext &unquantified(GQLParser::PathFactorContext &factor) {
    auto &primary = require(dynamic_cast<GQLParser::PfPathPrimaryContext *>(&factor), factor);
    auto &element = require(
        dynamic_cast<GQLParser::PpElementPatternContext *>(primary.pathPrimary()), primary);
    return *element.elementPattern();
}

GQLParser::GraphPatternContext &pattern(GQLParser::SimpleQueryStatementContext &clause) {
    auto &primitive = require(clause.primitiveQueryStatement(), clause);
    auto &match = require(primitive.matchStatement(), primitive);
    auto &simple = require(match.simpleMatchStatement(), match);
    auto &table = *simple.graphPatternBindingTable();
    deny(table.graphPatternYieldClause());
    return *table.graphPattern();
}

void extract_path(GQLParser::GraphPatternContext &graph, ReadView &read, bool native) {
    deny(graph.matchMode());
    deny(graph.keepClause());
    auto paths = graph.pathPatternList()->pathPattern();
    if (paths.size() != 1) {
        reject(*graph.pathPatternList());
    }
    auto &path = *paths.front();
    deny(path.pathVariableDeclaration());
    deny(path.pathPatternPrefix());
    auto &term = require(
        dynamic_cast<GQLParser::PpePathTermContext *>(path.pathPatternExpression()), path);
    auto factors = term.pathTerm()->pathFactor();
    if (factors.size() != 3) {
        reject(term);
    }
    read.left = node(unquantified(*factors[0]));
    read.relationship_label = relationship(unquantified(*factors[1]), native, read);
    read.right = node(unquantified(*factors[2]));
}

GQLParser::ValueExpressionPrimaryContext &primary(GQLParser::ValueExpressionContext &expression) {
    auto &primary = require(dynamic_cast<GQLParser::PrimaryExprAltContext *>(&expression), expression);
    return *primary.valueExpressionPrimary();
}

Property property(GQLParser::ValueExpressionContext &expression) {
    auto &outer = primary(expression);
    auto &name = require(outer.propertyName(), outer);
    auto &inner = *outer.valueExpressionPrimary();
    auto &variable = require(inner.bindingVariableReference(), inner);
    return {span(variable), span(name)};
}

Projection projection(GQLParser::ReturnItemContext &item, bool native) {
    auto *alias = item.returnItemAlias();
    if (!alias && !native) reject(item);
    return {property(*item.aggregatingValueExpression()->valueExpression()),
        alias ? span(*alias->identifier()) : Span{}};
}

Comparison comparison(GQLParser::CompOpContext &operation) {
    switch (operation.getStart()->getType()) {
        case GQLParser::EQUALS_OPERATOR: return eq;
        case GQLParser::NOT_EQUALS_OPERATOR: return ne;
        case GQLParser::LEFT_ANGLE_BRACKET: return lt;
        case GQLParser::LESS_THAN_OR_EQUALS_OPERATOR: return le;
        case GQLParser::RIGHT_ANGLE_BRACKET: return gt;
        case GQLParser::GREATER_THAN_OR_EQUALS_OPERATOR: return ge;
        default: reject(operation);
    }
}

void extract_literal(GQLParser::ValueExpressionContext &expression, Predicate &predicate, bool native) {
    auto *signed_expression = dynamic_cast<GQLParser::SignedExprAltContext *>(&expression);
    auto &value = primary(signed_expression ? *signed_expression->valueExpression() : expression);
    auto &specification = require(value.unsignedValueSpecification(), value);
    if (native && !signed_expression && specification.generalValueSpecification()) {
        auto &dynamic = require(specification.generalValueSpecification()->dynamicParameterSpecification(), specification);
        predicate.literal_kind = parameter;
        predicate.literal_text = span(dynamic);
        return;
    }
    auto &literal = require(specification.unsignedLiteral(), specification);
    if (auto *numeric = literal.unsignedNumericLiteral()) {
        auto &exact = require(numeric->exactNumericLiteral(), *numeric);
        auto &number = require(exact.unsignedInteger(), exact);
        auto &decimal = require(number.UNSIGNED_DECIMAL_INTEGER(), number);
        predicate.literal_kind = signed_expression && signed_expression->MINUS_SIGN()
            ? negative_integer
            : integer;
        predicate.literal_text = span(*decimal.getSymbol(), *decimal.getSymbol());
        return;
    }
    if (signed_expression) {
        reject(*signed_expression);
    }
    auto &general = *literal.generalLiteral();
    if (auto *value = general.BOOLEAN_LITERAL()) {
        predicate.literal_kind = boolean;
        predicate.literal_text = span(*value->getSymbol(), *value->getSymbol());
        return;
    }
    auto &value_string = require(general.characterStringLiteral(), general);
    predicate.literal_kind = string;
    predicate.literal_text = span(value_string);
}

Predicate predicate(GQLParser::SearchConditionContext &condition, PredicateStyle style, bool native) {
    auto &expression = *condition.booleanValueExpression()->valueExpression();
    auto &test = require(dynamic_cast<GQLParser::ComparisonExprAltContext *>(&expression), expression);
    Predicate result{};
    result.style = style;
    result.comparison = comparison(*test.compOp());
    result.property = property(*test.valueExpression(0));
    extract_literal(*test.valueExpression(1), result, native);
    return result;
}

GQLParser::AmbientLinearQueryStatementContext &ambient(GQLParser::GqlProgramContext &program) {
    deny(program.sessionCloseCommand());
    auto &activity = require(program.programActivity(), program);
    auto &transaction = require(activity.transactionActivity(), activity);
    deny(transaction.startTransactionCommand());
    deny(transaction.endTransactionCommand());
    auto &procedure = require(transaction.procedureSpecification(), transaction);
    auto &body = *procedure.procedureBody();
    deny(body.atSchemaClause());
    deny(body.bindingVariableDefinitionBlock());
    auto &block = *body.statementBlock();
    auto next = block.nextStatement();
    if (!next.empty()) {
        reject(*next.front());
    }
    auto &statement = *block.statement();
    auto &query = require(statement.compositeQueryStatement(), statement);
    auto &composite = *query.compositeQueryExpression();
    deny(composite.queryConjunction());
    auto &linear = *composite.compositeQueryPrimary()->linearQueryStatement();
    return require(linear.ambientLinearQueryStatement(), linear);
}

void extract_read(GQLParser::GqlProgramContext &program, ParsedRead &result, bool native) {
    auto &query = ambient(program);
    auto &prefix = require(query.simpleLinearQueryStatement(), query);
    auto clauses = prefix.simpleQueryStatement();
    auto &graph = pattern(*clauses.front());
    extract_path(graph, result.view, native);

    if (auto *where_clause = graph.graphPatternWhereClause()) {
        result.view.predicate = predicate(*where_clause->searchCondition(), where, native);
    }
    if (clauses.size() > 1) {
        auto &clause = *clauses[1];
        if (clauses.size() != 2 || result.view.predicate.style != absent) {
            reject(clause);
        }
        auto &primitive = require(clause.primitiveQueryStatement(), clause);
        auto &filter_clause = require(primitive.filterStatement(), primitive);
        auto *search = filter_clause.whereClause() ? filter_clause.whereClause()->searchCondition()
                                                  : filter_clause.searchCondition();
        result.view.predicate = predicate(*search, filter, native);
    }

    auto &ending = *query.primitiveResultStatement();
    if (auto *paging = ending.orderByAndPageStatement()) {
        if (!native) reject(*paging);
        deny(paging->offsetClause());
        if (auto *limit = paging->limitClause()) {
            auto &value = require(limit->nonNegativeIntegerSpecification()->unsignedInteger(), *limit);
            auto &integer = require(value.UNSIGNED_DECIMAL_INTEGER(), value);
            result.view.limit = span(*integer.getSymbol(), *integer.getSymbol());
        }
        if (auto *order = paging->orderByClause()) {
            for (auto *key : order->sortSpecificationList()->sortSpecification()) {
                deny(key->nullOrdering());
                auto &expr = primary(*key->sortKey()->aggregatingValueExpression()->valueExpression());
                auto &name = require(expr.bindingVariableReference(), expr);
                auto *direction = key->orderingSpecification();
                result.sort_keys.push_back({span(name),
                    direction && (direction->DESC() || direction->DESCENDING())});
            }
            result.view.sort_keys = result.sort_keys.data();
            result.view.sort_count = result.sort_keys.size();
        }
    }
    auto &body = *require(ending.returnStatement(), ending).returnStatementBody();
    if (auto *quantifier = body.setQuantifier()) {
        if (!native) reject(*quantifier);
        result.view.distinct = quantifier->DISTINCT() != nullptr;
    }
    deny(body.groupByClause());
    auto &items = require(body.returnItemList(), body);
    for (auto *item : items.returnItem()) {
        result.projections.push_back(projection(*item, native));
    }
    result.view.projections = result.projections.data();
    result.view.projection_count = result.projections.size();
}

int delimiter_delta(std::size_t type) {
    switch (type) {
        case GQLLexer::LEFT_PAREN:
        case GQLLexer::LEFT_BRACE:
        case GQLLexer::LEFT_BRACKET:
        case GQLLexer::MINUS_LEFT_BRACKET:
        case GQLLexer::LEFT_ARROW_BRACKET:
        case GQLLexer::LEFT_ARROW_TILDE_BRACKET:
        case GQLLexer::TILDE_LEFT_BRACKET: return 1;
        case GQLLexer::RIGHT_PAREN:
        case GQLLexer::RIGHT_BRACE:
        case GQLLexer::RIGHT_BRACKET:
        case GQLLexer::RIGHT_BRACKET_MINUS:
        case GQLLexer::RIGHT_BRACKET_TILDE:
        case GQLLexer::BRACKET_RIGHT_ARROW:
        case GQLLexer::BRACKET_TILDE_RIGHT_ARROW: return -1;
        default: return 0;
    }
}

void check_complexity(antlr4::CommonTokenStream &tokens) {
    std::size_t count = 0;
    std::size_t depth = 0;
    for (const auto *token : tokens.getTokens()) {
        if (token->getChannel() != Token::DEFAULT_CHANNEL || token->getType() == Token::EOF) {
            continue;
        }
        if (++count > max_lexer_tokens) {
            throw at(limit, token);
        }
        const auto change = delimiter_delta(token->getType());
        if (change > 0 && ++depth > max_delimiter_depth) {
            throw at(limit, token);
        }
        if (change < 0 && depth != 0) {
            --depth;
        }
    }
}

std::unique_ptr<ParsedRead> parse(std::string_view input, bool native) {
    if (input.size() > max_input_bytes) {
        throw at(limit, nullptr);
    }
    // The ANTLR stream drops the BOM, which would shift the returned source spans.
    if (input.substr(0, 3) == "\xef\xbb\xbf") {
        throw Diagnostic{syntax, 1, 0};
    }
    antlr4::ANTLRInputStream stream(input);
    GQLLexer lexer(&stream);
    Errors errors;
    lexer.removeErrorListeners();
    lexer.addErrorListener(&errors);
    antlr4::CommonTokenStream tokens(&lexer);
    tokens.fill();
    if (errors.first.status) {
        throw errors.first;
    }
    check_complexity(tokens);

    GQLParser parser(&tokens);
    parser.removeErrorListeners();
    parser.addErrorListener(&errors);
    parser.setErrorHandler(std::make_shared<antlr4::BailErrorStrategy>());
    GQLParser::GqlProgramContext *program = nullptr;
    try {
        program = parser.gqlProgram();
    } catch (const antlr4::ParseCancellationException &) {
        throw errors.first.status ? errors.first : at(syntax, parser.getCurrentToken());
    }
    if (errors.first.status || !program || !program->EOF() || tokens.LA(1) != Token::EOF) {
        throw errors.first.status ? errors.first : at(syntax, parser.getCurrentToken());
    }
    auto result = std::make_unique<ParsedRead>();
    extract_read(*program, *result, native);
    return result;
}

} // namespace

extern "C" ParsedRead *qw_gql_parse(const char *bytes, std::size_t length, bool native, Diagnostic *diagnostic) noexcept {
    *diagnostic = {};
    try {
        return parse(std::string_view(bytes, length), native).release();
    } catch (const Diagnostic &failure) {
        *diagnostic = failure;
    } catch (...) {
        *diagnostic = {internal, 0, 0};
    }
    return nullptr;
}

extern "C" const ReadView *qw_gql_read(const ParsedRead *read) noexcept {
    return &read->view;
}

extern "C" void qw_gql_destroy(ParsedRead *read) noexcept {
    delete read;
}

extern "C" bool qw_gql_parameters(const char *text, std::size_t length,
    bool (*visit)(void*, const char*, std::size_t), void *output) noexcept {
    try {
        if (length > max_input_bytes) return false;
        antlr4::ANTLRInputStream stream(std::string_view{text, length});
        GQLLexer lexer(&stream);
        lexer.removeErrorListeners();
        for (auto token = lexer.nextToken(); token->getType() != Token::EOF; token = lexer.nextToken()) {
            if (token->getType() != GQLLexer::GENERAL_PARAMETER_REFERENCE) continue;
            auto name = token->getText();
            if (!visit(output, name.data() + 1, name.size() - 1)) return false;
        }
        return true;
    } catch (...) {
        return false;
    }
}
