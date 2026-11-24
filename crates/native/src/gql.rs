use std::ptr::NonNull;

use rusty_quack_core::gql::{
    Comparison, Literal, Location, NodePattern, ParseError, ParseErrorKind, ParsedRead, Predicate,
    PredicateStyle, Projection, Property, SourceSpan,
};

#[repr(C)]
#[derive(Default)]
struct Diagnostic {
    status: i32,
    line: usize,
    column: usize,
}

impl From<Diagnostic> for ParseError {
    fn from(diagnostic: Diagnostic) -> Self {
        let kind = match diagnostic.status {
            1 => ParseErrorKind::Syntax,
            2 => ParseErrorKind::Unsupported,
            3 => ParseErrorKind::Limit,
            _ => ParseErrorKind::Internal,
        };
        let location = (diagnostic.line != 0).then_some(Location {
            line: diagnostic.line,
            column: diagnostic.column,
        });
        Self { kind, location }
    }
}

#[repr(C)]
#[derive(Clone, Copy)]
struct Span {
    begin: usize,
    end: usize,
    line: usize,
    column: usize,
}

impl Span {
    fn location(self) -> Location {
        Location {
            line: self.line,
            column: self.column,
        }
    }

    fn unsupported(self) -> ParseError {
        ParseError {
            kind: ParseErrorKind::Unsupported,
            location: Some(self.location()),
        }
    }
}

#[repr(C)]
struct RawNode {
    variable: Span,
    label: Span,
}

#[repr(C)]
struct RawProperty {
    variable: Span,
    name: Span,
}

#[repr(C)]
struct RawProjection {
    property: RawProperty,
    alias: Span,
}

#[repr(C)]
struct RawPredicate {
    style: i32,
    comparison: i32,
    literal_kind: i32,
    property: RawProperty,
    literal_text: Span,
}

#[repr(C)]
struct RawSort {
    alias: Span,
    descending: bool,
}

#[repr(C)]
struct RawRead {
    left: RawNode,
    relationship_label: Span,
    right: RawNode,
    predicate: RawPredicate,
    projections: *const RawProjection,
    projection_count: usize,
    relationship_variable: Span,
    distinct: bool,
    limit: Span,
    sort_keys: *const RawSort,
    sort_count: usize,
    path_variable: Span,
}

#[repr(C)]
struct RawHandle {
    _opaque: [u8; 0],
}

unsafe extern "C" {
    fn qw_gql_parse(
        bytes: *const u8,
        length: usize,
        native: bool,
        diagnostic: *mut Diagnostic,
    ) -> *mut RawHandle;
    fn qw_gql_read(parsed: *const RawHandle) -> *const RawRead;
    fn qw_gql_destroy(parsed: *mut RawHandle);
}

struct OwnedRead(NonNull<RawHandle>);

impl Drop for OwnedRead {
    fn drop(&mut self) {
        // SAFETY: The parse call transfers exactly one handle, which this owner releases once.
        unsafe { qw_gql_destroy(self.0.as_ptr()) };
    }
}

impl OwnedRead {
    fn view(&self) -> &RawRead {
        // SAFETY: This private accessor returns an immutable view inside the live handle.
        unsafe { &*qw_gql_read(self.0.as_ptr()) }
    }
}

impl RawRead {
    fn projections(&self) -> &[RawProjection] {
        // SAFETY: A successful parse builds one or more projections in the live handle.
        // Native code does not mutate or reallocate that array after returning.
        unsafe { std::slice::from_raw_parts(self.projections, self.projection_count) }
    }
}

struct Input<'a> {
    text: &'a str,
    byte_offsets: Vec<usize>,
}

impl<'a> Input<'a> {
    fn new(text: &'a str) -> Self {
        let mut byte_offsets: Vec<_> = text.char_indices().map(|(index, _)| index).collect();
        byte_offsets.push(text.len());
        Self { text, byte_offsets }
    }

    fn text(&self, span: Span) -> Result<&'a str, ParseError> {
        let span = self.source_span(span)?;
        self.text
            .get(span.start..span.end)
            .ok_or_else(internal_error)
    }

    fn source_span(&self, span: Span) -> Result<SourceSpan, ParseError> {
        self.byte_offsets
            .get(span.begin)
            .zip(self.byte_offsets.get(span.end))
            .map(|(&start, &end)| SourceSpan {
                start,
                end,
                location: span.location(),
            })
            .ok_or_else(internal_error)
    }

    fn identifier(&self, span: Span) -> Result<String, ParseError> {
        let text = self.text(span)?;
        let mut bytes = text.bytes();
        if bytes
            .next()
            .is_some_and(|b| b.is_ascii_alphabetic() || b == b'_')
            && bytes.all(|b| b.is_ascii_alphanumeric() || b == b'_')
        {
            return Ok(text.to_owned());
        }
        Err(span.unsupported())
    }

    fn node(&self, node: &RawNode) -> Result<NodePattern, ParseError> {
        Ok(NodePattern {
            variable: self.identifier(node.variable)?,
            variable_span: self.source_span(node.variable)?,
            label: self.identifier(node.label)?,
        })
    }

    fn property(&self, property: &RawProperty) -> Result<Property, ParseError> {
        Ok(Property {
            variable: self.identifier(property.variable)?,
            variable_span: self.source_span(property.variable)?,
            name: if property.name.line == 0 {
                String::new()
            } else {
                self.identifier(property.name)?
            },
        })
    }

    fn literal(&self, predicate: &RawPredicate) -> Result<Literal, ParseError> {
        let span = predicate.literal_text;
        let text = self.text(span)?;
        let literal = match predicate.literal_kind {
            0 if text.eq_ignore_ascii_case("true") => Some(Literal::Boolean(true)),
            0 if text.eq_ignore_ascii_case("false") => Some(Literal::Boolean(false)),
            0 => None,
            1 => text.parse().ok().map(Literal::Integer),
            2 => format!("-{text}").parse().ok().map(Literal::Integer),
            3 => decode_string(text).map(Literal::String),
            4 => text
                .strip_prefix('$')
                .map(|name| Literal::Parameter(name.to_owned())),
            _ => return Err(internal_error()),
        };
        literal.ok_or_else(|| span.unsupported())
    }

    fn predicate(&self, predicate: &RawPredicate) -> Result<Option<Predicate>, ParseError> {
        let style = match predicate.style {
            0 => return Ok(None),
            1 => PredicateStyle::Where,
            2 => PredicateStyle::Filter,
            _ => return Err(internal_error()),
        };
        let comparison = match predicate.comparison {
            0 => Comparison::Eq,
            1 => Comparison::Ne,
            2 => Comparison::Lt,
            3 => Comparison::Le,
            4 => Comparison::Gt,
            5 => Comparison::Ge,
            _ => return Err(internal_error()),
        };
        Ok(Some(Predicate {
            style,
            comparison,
            property: self.property(&predicate.property)?,
            literal: self.literal(predicate)?,
        }))
    }

    fn read(&self, raw: &RawRead) -> Result<ParsedRead, ParseError> {
        let projections = raw
            .projections()
            .iter()
            .map(|item| {
                Ok(Projection {
                    property: self.property(&item.property)?,
                    alias: if item.alias.line == 0 {
                        String::new()
                    } else {
                        self.identifier(item.alias)?
                    },
                    alias_span: self.source_span(item.alias)?,
                })
            })
            .collect::<Result<_, ParseError>>()?;
        Ok(ParsedRead {
            path_variable: (raw.path_variable.line != 0)
                .then(|| self.identifier(raw.path_variable))
                .transpose()?,
            left: self.node(&raw.left)?,
            relationship_label: if raw.relationship_label.line == 0 {
                String::new()
            } else {
                self.identifier(raw.relationship_label)?
            },
            relationship_variable: (raw.relationship_variable.line != 0)
                .then(|| self.identifier(raw.relationship_variable))
                .transpose()?,
            distinct: raw.distinct,
            limit: (raw.limit.line != 0)
                .then(|| {
                    self.text(raw.limit)?
                        .parse::<u64>()
                        .map_err(|_| raw.limit.unsupported())
                })
                .transpose()?,
            order: if raw.sort_count == 0 {
                Vec::new()
            } else {
                // The native parser owns this immutable array until OwnedRead drops.
                unsafe { std::slice::from_raw_parts(raw.sort_keys, raw.sort_count) }
                    .iter()
                    .map(|key| Ok((self.identifier(key.alias)?, key.descending)))
                    .collect::<Result<_, ParseError>>()?
            },
            right: (raw.right.variable.line != 0)
                .then(|| self.node(&raw.right))
                .transpose()?,
            predicate: self.predicate(&raw.predicate)?,
            projections,
        })
    }
}

fn internal_error() -> ParseError {
    ParseError {
        kind: ParseErrorKind::Internal,
        location: None,
    }
}

fn decode_string(text: &str) -> Option<String> {
    let delimiter = match text.chars().next()? {
        delimiter @ ('\'' | '"') => delimiter,
        _ => return None,
    };
    let contents = text.strip_prefix(delimiter)?.strip_suffix(delimiter)?;
    let mut chars = contents.chars();
    let mut decoded = String::with_capacity(contents.len());
    while let Some(character) = chars.next() {
        let character = match character {
            quote if quote == delimiter => {
                if chars.next()? != delimiter {
                    return None;
                }
                delimiter
            }
            '\\' => match chars.next()? {
                escaped @ ('\\' | '\'' | '"' | '`') => escaped,
                't' => '\t',
                'b' => '\u{0008}',
                'n' => '\n',
                'r' => '\r',
                'f' => '\u{000c}',
                'u' => decode_unicode_escape(&mut chars, 4)?,
                'U' => decode_unicode_escape(&mut chars, 6)?,
                _ => return None,
            },
            ordinary => ordinary,
        };
        if character == '\0' {
            return None;
        }
        decoded.push(character);
    }
    Some(decoded)
}

fn decode_unicode_escape(chars: &mut std::str::Chars<'_>, digits: usize) -> Option<char> {
    let mut code_point = 0;
    for _ in 0..digits {
        code_point = (code_point << 4) | chars.next()?.to_digit(16)?;
    }
    char::from_u32(code_point)
}

pub fn parse(input: &str) -> Result<ParsedRead, ParseError> {
    parse_with_mode(input, false)
}

pub(crate) fn parse_native(input: &str) -> Result<ParsedRead, ParseError> {
    parse_with_mode(input, true)
}

fn parse_with_mode(input: &str, native: bool) -> Result<ParsedRead, ParseError> {
    let mut diagnostic = Diagnostic::default();
    // SAFETY: The parser reads the UTF-8 input during the call and fills the diagnostic.
    // The output owns its parsed fields and retains offsets, never a Rust string pointer.
    let raw = unsafe { qw_gql_parse(input.as_ptr(), input.len(), native, &mut diagnostic) };
    let parsed = OwnedRead(NonNull::new(raw).ok_or_else(|| ParseError::from(diagnostic))?);
    Input::new(input).read(parsed.view())
}

#[cfg(test)]
mod tests;
