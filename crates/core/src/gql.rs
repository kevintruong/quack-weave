//! Owned input to the bounded GQL compiler. Native parser handles stay in the adapter.

#[derive(Debug, Eq, PartialEq)]
pub struct ParsedRead {
    pub left: NodePattern,
    pub relationship_label: String,
    pub relationship_variable: Option<String>,
    pub distinct: bool,
    pub order: Vec<(String, bool)>,
    pub limit: Option<u64>,
    pub right: NodePattern,
    pub predicate: Option<Predicate>,
    pub projections: Vec<Projection>,
}

#[derive(Debug, Eq, PartialEq)]
pub struct NodePattern {
    pub variable: String,
    pub variable_span: SourceSpan,
    pub label: String,
}

#[derive(Debug, Eq, PartialEq)]
pub struct Property {
    pub variable: String,
    pub variable_span: SourceSpan,
    pub name: String,
}

#[derive(Debug, Eq, PartialEq)]
pub struct Projection {
    pub property: Property,
    pub alias: String,
    pub alias_span: SourceSpan,
}

#[derive(Debug, Eq, PartialEq)]
pub struct Predicate {
    pub style: PredicateStyle,
    pub property: Property,
    pub comparison: Comparison,
    pub literal: Literal,
}

#[derive(Debug, Copy, Clone, Eq, PartialEq)]
pub enum PredicateStyle {
    Where,
    Filter,
}

#[derive(Debug, Copy, Clone, Eq, PartialEq)]
pub enum Comparison {
    Eq,
    Ne,
    Lt,
    Le,
    Gt,
    Ge,
}

#[derive(Debug, Eq, PartialEq)]
pub enum Literal {
    Parameter(String),
    Boolean(bool),
    Integer(i64),
    String(String),
}

#[derive(Debug, Copy, Clone, Eq, PartialEq)]
pub enum ParseErrorKind {
    Syntax,
    Unsupported,
    Limit,
    Internal,
    Unavailable,
}

#[derive(Debug, Copy, Clone, Eq, PartialEq)]
pub struct ParseError {
    pub kind: ParseErrorKind,
    pub location: Option<Location>,
}

#[derive(Debug, Copy, Clone, Eq, PartialEq)]
pub struct Location {
    /// One-based line number.
    pub line: usize,
    /// Zero-based Unicode code point offset within the line.
    pub column: usize,
}

#[derive(Debug, Copy, Clone, Eq, PartialEq)]
pub struct SourceSpan {
    /// Start and exclusive end byte offsets in the UTF-8 input.
    pub start: usize,
    pub end: usize,
    pub location: Location,
}
