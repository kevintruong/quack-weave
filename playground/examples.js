export const examples = [
  {
    title: "Explore citations",
    mode: "cypher",
    detail: "Follow outgoing citation links from paper 100 in Ladybug.",
    sql: `MATCH (source:Document)-[:LINKS_TO]->(cited:Document)
WHERE source.id = 100
RETURN cited.id AS paper_id, cited.title AS title
ORDER BY paper_id;`,
  },
  {
    title: "Rank papers",
    mode: "sql",
    detail: "Rank the sample papers by the citation counts in DuckDB.",
    sql: `SELECT id, title, venue, year, citation_count
FROM papers
ORDER BY citation_count DESC
LIMIT 5;`,
  },
  {
    title: "Join both engines",
    engine: "SQL + Cypher",
    mode: "sql",
    detail: "Use GRAPH_TABLE to join Ladybug citations to publication data in DuckDB.",
    sql: `SELECT p.id, p.title, p.venue, p.citation_count
FROM papers AS p
JOIN GRAPH_TABLE (
  kg MATCH (source:Document)-[link:LINKS_TO]->(cited:Document)
  WHERE source.id = 100
  COLUMNS (cited.id AS paper_id)
) AS cited ON p.id = cited.paper_id
ORDER BY p.citation_count DESC;`,
  },
  {
    title: "Follow two hops",
    mode: "cypher",
    detail: "Find the papers that your starting paper reaches through one intermediate citation.",
    sql: `MATCH (source:Document)-[:LINKS_TO]->(via:Document)
      -[:LINKS_TO]->(cited:Document)
WHERE source.id = 100
RETURN via.title AS via_title, cited.title AS cited_title
ORDER BY via_title, cited_title;`,
  },
];

export const publicExamples = [
  {
    title: "Preview nodes",
    mode: "cypher",
    detail: "Inspect labels and properties on up to ten nodes from the selected graph.",
    sql: "MATCH (n) RETURN n LIMIT 10;",
  },
  {
    title: "Count relationships",
    engine: "SQL + Cypher",
    mode: "sql",
    detail: "Run a graph-wide count in Ladybug and return it to DuckDB.",
    sql: `SELECT * FROM qw_query('kg', 'cypher',
  $$MATCH ()-[r]->() RETURN count(r) AS edges$$,
  schema := 'edges BIGINT');`,
  },
];
