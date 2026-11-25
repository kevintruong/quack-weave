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
    mode: "sql",
    detail: "Find citations in Ladybug, then join them to venue and ranking data in DuckDB.",
    sql: `WITH cited AS (
  SELECT paper_id
  FROM qw_query(
    'kg', 'cypher',
    $$MATCH (source:Document)-[:LINKS_TO]->(cited:Document)
      WHERE source.id = 100
      RETURN cited.id AS paper_id$$,
    schema := 'paper_id BIGINT'
  )
)
SELECT p.id, p.title, p.venue, p.citation_count
FROM papers AS p
JOIN cited ON p.id = cited.paper_id
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
