cmake_minimum_required(VERSION 3.16)
project(qw_gql_parser LANGUAGES CXX)

file(GLOB_RECURSE ANTLR_SOURCES CONFIGURE_DEPENDS "${QW_ANTLR_SOURCE}/*.cpp")
add_library(qw_gql_parser STATIC
    ../src/gql_parser.cpp
    "${QW_GQL_GENERATED}/GQLLexer.cpp"
    "${QW_GQL_GENERATED}/GQLParser.cpp"
    ${ANTLR_SOURCES}
)
target_include_directories(qw_gql_parser PRIVATE "${QW_ANTLR_SOURCE}" "${QW_GQL_GENERATED}")
# Ladybug also statically links ANTLR. Isolate its namespaces and global generated XPath lexer.
target_compile_definitions(qw_gql_parser PRIVATE
    ANTLR4CPP_STATIC
    antlr4=qw_gql_antlr4
    antlrcpp=qw_gql_antlrcpp
    XPathLexer=QwGqlXPathLexer
)
target_compile_features(qw_gql_parser PRIVATE cxx_std_17)
set_target_properties(qw_gql_parser PROPERTIES
    POSITION_INDEPENDENT_CODE ON
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN ON
)
