use super::*;

#[test]
fn gql_read_parser_accepts_a_complete_fixed_directed_match() {
    let read = parse(
        "MATCH (a:Document)-[:LINKS_TO]->(b:Document) WHERE a.id = -42 \
         RETURN b.id AS document_id, a.title AS title",
    )
    .unwrap();
    assert_eq!(read.left.variable, "a");
    assert_eq!(read.left.label, "Document");
    assert_eq!(read.relationship_label, "LINKS_TO");
    assert_eq!(read.right.variable, "b");
    assert_eq!(read.right.label, "Document");
    let predicate = read.predicate.unwrap();
    assert_eq!(predicate.style, PredicateStyle::Where);
    assert_eq!(predicate.comparison, Comparison::Eq);
    assert_eq!(predicate.property.variable, "a");
    assert_eq!(predicate.property.name, "id");
    assert_eq!(predicate.literal, Literal::Integer(-42));
    assert_eq!(read.projections.len(), 2);
    assert_eq!(read.projections[0].alias, "document_id");
    assert_eq!(read.projections[0].property.name, "id");
    assert_eq!(read.projections[1].alias, "title");
    assert_eq!(read.projections[1].property.name, "title");
}

#[test]
fn gql_read_parser_preserves_filter_and_string_literals() {
    let input = "MATCH (a:A)-[:E]->(b:B) FILTER a.name = 'Zoë; O''Brien' RETURN b.id AS id";
    let read = parse(input).unwrap();
    assert_eq!(
        &input[read.left.variable_span.start..read.left.variable_span.end],
        "a"
    );
    let predicate = read.predicate.unwrap();
    assert_eq!(predicate.style, PredicateStyle::Filter);
    assert_eq!(predicate.literal, Literal::String("Zoë; O'Brien".into()));
    let projection = &read.projections[0];
    assert_eq!(projection.alias, "id");
    let alias = projection.alias_span;
    assert_eq!(alias.start, input.len() - 2);
    assert_eq!(alias.end, input.len());
    assert_eq!(alias.location.column, input[..alias.start].chars().count());
    let variable = projection.property.variable_span;
    assert_eq!(variable.start, input.find("b.id").unwrap());
    assert_eq!(&input[variable.start..variable.end], "b");

    let read =
        parse("match (a:A)-[:E]->(b:B) filter where b.visible <> FALSE return b.id as id").unwrap();
    let predicate = read.predicate.unwrap();
    assert_eq!(predicate.style, PredicateStyle::Filter);
    assert_eq!(predicate.comparison, Comparison::Ne);
    assert_eq!(predicate.literal, Literal::Boolean(false));
}

#[test]
fn gql_read_parser_decodes_gql_escape_sequences() {
    let read = parse(
        r#"MATCH (a:A)-[:E]->(b:B) WHERE a.name = 'O\'Brien\\ \"\t\n\r\b\f\u00E9\U01F4A9' RETURN b.id AS id"#,
    )
    .unwrap();
    assert_eq!(
        read.predicate.unwrap().literal,
        Literal::String("O'Brien\\ \"\t\n\r\u{0008}\u{000c}é💩".into())
    );
    for escaped in [r"\u0000", r"\uD800", r"\U110000"] {
        let input = format!("MATCH (a:A)-[:E]->(b:B) WHERE a.name = '{escaped}' RETURN b.id AS id");
        assert_eq!(parse(&input).unwrap_err().kind, ParseErrorKind::Unsupported);
    }
}

#[test]
fn gql_read_parser_recognizes_the_signed_integer_boundary() {
    let read =
        parse("MATCH (a:A)-[:E]->(b:B) WHERE a.id = - 9223372036854775808 RETURN b.id AS id")
            .unwrap();
    assert_eq!(read.predicate.unwrap().literal, Literal::Integer(i64::MIN));
    let error = parse("MATCH (a:A)-[:E]->(b:B) WHERE a.id = 9223372036854775808 RETURN b.id AS id")
        .unwrap_err();
    assert_eq!(error.kind, ParseErrorKind::Unsupported);
}

#[test]
fn gql_read_parser_requires_a_complete_program() {
    assert_eq!(
        parse("MATCH (a:A)-[:E]->(b:B) RETURN b.id AS id; INSERT (:A)")
            .unwrap_err()
            .kind,
        ParseErrorKind::Syntax
    );
    assert_eq!(
        parse("MATCH (a:A)-[:E]->(b:B) RETURN b.id AS")
            .unwrap_err()
            .kind,
        ParseErrorKind::Syntax
    );
    assert_eq!(
        parse("MATCH (a:A)-[:E]->(b:B) RETURN b.id AS id NEXT RETURN 1 AS n")
            .unwrap_err()
            .kind,
        ParseErrorKind::Unsupported
    );
}

#[test]
fn gql_read_parser_classifies_valid_programs_outside_the_bounded_subset() {
    for input in [
        "INSERT (:A)",
        "MATCH (a:A)-[:E]->(b:B) DELETE b",
        "MATCH (a:A)-[:E]->(b:B) RETURN b.id AS id NEXT INSERT (:A)",
        "OPTIONAL MATCH (a:A)-[:E]->(b:B) RETURN b.id AS id",
        "{ MATCH (a:A)-[:E]->(b:B) RETURN b.id AS id }",
        "MATCH (a:A)-[:E]->(b:B) MATCH (b:B)-[:E]->(c:C) RETURN c.id AS id",
        "MATCH (:A)-[:E]->(b:B) RETURN b.id AS id",
        "MATCH (a)-[:E]->(b:B) RETURN b.id AS id",
        "MATCH (a:A {id:42})-[:E]->(b:B) RETURN b.id AS id",
        "MATCH (a:A)-[e:E]->(b:B) RETURN b.id AS id",
        "MATCH (a:A)-[:E]->(b:B) RETURN b AS id",
        "MATCH (a:A)-[:E]->(b:B) RETURN b.a.id AS id",
        "MATCH (a:A)-[:E]->(b:B) RETURN count(b.id) AS id",
        "MATCH (a:A)-[:E]->(b:B) RETURN b.id AS `id`",
    ] {
        assert_eq!(
            parse(input).unwrap_err().kind,
            ParseErrorKind::Unsupported,
            "{input}"
        );
    }
}

#[test]
fn gql_read_parser_locates_invalid_input_without_source_text() {
    let line = "WHERE a.name = 'Zoë; O''Brien' ";
    let input = format!("MATCH (a:A)-[:E]->(b:B)\n{line}; RETURN b.id AS id");
    assert_eq!(
        parse(&input),
        Err(ParseError {
            kind: ParseErrorKind::Syntax,
            location: Some(Location {
                line: 2,
                column: line.chars().count()
            }),
        })
    );
}

#[test]
fn gql_read_parser_bounds_input_bytes_tokens_and_nesting() {
    let read = "MATCH (a:A)-[:E]->(b:B) RETURN b.id AS id";
    let at_byte_limit = format!("{read}{}", " ".repeat(16 * 1024 - read.len()));
    assert!(parse(&at_byte_limit).is_ok());
    assert_eq!(
        parse(&format!("{at_byte_limit} ")).unwrap_err().kind,
        ParseErrorKind::Limit
    );

    let projections = (0..39)
        .map(|index| format!("b.id AS id{index}"))
        .collect::<Vec<_>>()
        .join(", ");
    let prefix = "MATCH (a:A)-[:E]->(b:B) WHERE a.id = +42 RETURN";
    assert_eq!(
        parse(&format!("{prefix} {projections}"))
            .unwrap()
            .projections
            .len(),
        39
    );
    assert_eq!(
        parse(&format!("{prefix} DISTINCT {projections}"))
            .unwrap_err()
            .kind,
        ParseErrorKind::Limit
    );

    for (depth, expected) in [
        (16, ParseErrorKind::Unsupported),
        (17, ParseErrorKind::Limit),
    ] {
        let input = format!(
            "MATCH (a:A)-[:E]->(b:B) RETURN {}b.id{} AS id",
            "(".repeat(depth),
            ")".repeat(depth),
        );
        assert_eq!(parse(&input).unwrap_err().kind, expected);
    }
}

#[test]
fn fixture_observer_parser() {
    use crate::test_observation::{capture, event, hex};

    fn span(input: &str, name: &str, span: SourceSpan) {
        let bytes = hex(&input.as_bytes()[span.start..span.end]);
        event(
            name,
            "ok",
            &format!(
                "{}:{}:{}:{}:{bytes}",
                span.start, span.end, span.location.line, span.location.column
            ),
        );
    }

    for (invocation, input) in [
        (
            "boolean",
            "MATCH (a:A)-[:E]->(b:B) WHERE a.active = TRUE RETURN b.id AS id",
        ),
        (
            "integer",
            "MATCH (a:A)-[:E]->(b:B) WHERE a.id = -9223372036854775808 RETURN b.id AS id",
        ),
        (
            "unicode",
            r"MATCH (a:A)-[:E]->(b:B) FILTER a.name = 'Zoë; O''Brien\\path\U01F4A9' RETURN b.id AS id",
        ),
        (
            "invalid_unicode",
            "MATCH (a:A)-[:E]->(b:B)\nWHERE a.name = 'Zoë; O''Brien' ; RETURN b.id AS id",
        ),
    ] {
        capture("observer.parser", invocation, None, || {
            event("input", "ok", &hex(input.as_bytes()));
            match parse(input) {
                Ok(read) => {
                    if let Some(predicate) = &read.predicate {
                        match &predicate.literal {
                            Literal::Boolean(value) => {
                                event("literal", "boolean", &value.to_string())
                            }
                            Literal::Integer(value) => {
                                event("literal", "integer", &value.to_string())
                            }
                            Literal::String(value) => {
                                event("literal", "string", &hex(value.as_bytes()))
                            }
                        }
                        span(input, "span_before", predicate.property.variable_span);
                    }
                    if let Some(projection) = read.projections.first() {
                        span(input, "span_after", projection.alias_span);
                    }
                }
                Err(error) => {
                    let location = error.location.map_or_else(String::new, |value| {
                        format!("{}:{}", value.line, value.column)
                    });
                    event("diagnostic", &format!("{:?}", error.kind), &location);
                }
            }
        });
    }
}
