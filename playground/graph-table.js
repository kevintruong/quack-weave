import { TokenType } from "@duckdb/duckdb-wasm";

// DuckDB token offsets are bytes and omit comments. Keep the original SQL and
// Cypher text between tokens so quotes, comments, and Unicode survive lowering.
export function lowerGraphTables(sql, { offsets, types }) {
  const bytes = new TextEncoder().encode(sql);
  const decoder = new TextDecoder();
  const text = (start, end) => decoder.decode(bytes.subarray(start, end));
  const token = index => index < offsets.length ? text(offsets[index], offsets[index + 1]) : "";
  const word = index => {
    if (types[index] !== TokenType.IDENTIFIER && types[index] !== TokenType.KEYWORD) return "";
    return token(index).match(/^[a-z_][a-z0-9_$]*/i)?.[0].toLowerCase() ?? "";
  };
  const operator = (index, value) => types[index] === TokenType.OPERATOR && token(index).startsWith(value);

  const graphTables = new Map();
  const pieces = [];
  let cursor = 0;
  for (let index = 0; index < offsets.length; index++) {
    if (word(index) !== "graph_table" || operator(index - 1, ".") ||
        !operator(index + 1, "(") || word(index + 3) !== "match") continue;
    if (word(index + 2) !== "kg") throw new Error("GRAPH_TABLE expects the PaperTrail graph alias kg.");

    let depth = 1;
    let columns = -1;
    let columnsEnd = -1;
    let end = index + 4;
    for (; end < offsets.length; end++) {
      if (depth === 1 && word(end) === "columns" && operator(end + 1, "(")) columns = end;
      if (operator(end, "(")) depth++;
      if (operator(end, ")")) {
        depth--;
        if (depth === 0) break;
        if (depth === 1 && columns !== -1) columnsEnd = end;
      }
    }
    if (depth !== 0 || columns === -1 || columnsEnd !== end - 1) {
      throw new Error("Use GRAPH_TABLE (kg MATCH … COLUMNS (…)) with COLUMNS at the end.");
    }

    const pattern = text(offsets[index + 3], offsets[columns]).trimEnd();
    const projections = text(offsets[columns + 1] + 1, offsets[columnsEnd]);
    const placeholder = `qw_graph_${crypto.randomUUID().replaceAll("-", "")}`;
    graphTables.set(placeholder, `${pattern}\nRETURN ${projections}`);
    pieces.push(text(cursor, offsets[index]), `${placeholder}()`);
    cursor = offsets[end] + 1;
    index = end;
  }
  if (graphTables.size === 0) return { statement: sql, graphTables };

  pieces.push(text(cursor));
  return { statement: pieces.join(""), graphTables };
}
