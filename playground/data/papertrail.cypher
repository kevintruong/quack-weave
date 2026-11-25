CREATE NODE TABLE Document(id INT64 PRIMARY KEY, title STRING);
CREATE REL TABLE LINKS_TO(FROM Document TO Document);
UNWIND [{id: 100, title: "Mapping Research Networks"}, {id: 101, title: "Vector Search for Archives"}, {id: 102, title: "The Long Tail of Citations"}, {id: 103, title: "Query Patterns in Open Collections"}, {id: 104, title: "Provenance in Digital Libraries"}, {id: 105, title: "Graph Sampling at the Edge"}, {id: 106, title: "Ranking Knowledge Sources"}, {id: 107, title: "Signals from Citation Trails"}, {id: 108, title: "A Survey of Research Graphs"}, {id: 109, title: "Link Prediction for Repositories"}, {id: 110, title: "Explaining Retrieval Decisions"}, {id: 111, title: "Reproducible Scholarly Search"}] AS paper
CREATE (:Document {id: paper.id, title: paper.title});
UNWIND [{source: 100, target: 101}, {source: 100, target: 102}, {source: 100, target: 105}, {source: 101, target: 103}, {source: 101, target: 104}, {source: 101, target: 108}, {source: 102, target: 106}, {source: 102, target: 108}, {source: 103, target: 104}, {source: 104, target: 108}, {source: 105, target: 106}, {source: 105, target: 109}, {source: 106, target: 108}, {source: 107, target: 100}, {source: 107, target: 102}, {source: 109, target: 104}, {source: 110, target: 101}, {source: 110, target: 104}, {source: 111, target: 104}, {source: 111, target: 108}] AS link
MATCH (source:Document), (target:Document)
WHERE source.id = link.source AND target.id = link.target
CREATE (source)-[:LINKS_TO]->(target);
CHECKPOINT;
