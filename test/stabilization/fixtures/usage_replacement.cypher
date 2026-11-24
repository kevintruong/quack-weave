CREATE NODE TABLE Document(id INT64 PRIMARY KEY);
CREATE REL TABLE LINKS_TO(FROM Document TO Document);
CREATE (:Document {id: 100});
CREATE (:Document {id: 201});
MATCH (a:Document {id: 100}), (b:Document {id: 201}) CREATE (a)-[:LINKS_TO]->(b);
MATCH (a:Document {id: 100}), (b:Document {id: 201}) CREATE (a)-[:LINKS_TO]->(b);
