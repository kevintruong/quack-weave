CREATE NODE TABLE airport(code STRING PRIMARY KEY);
CREATE REL TABLE route(FROM airport TO airport, rid INT64, dist INT64);
UNWIND ['ATL', 'BOS', 'LAX', 'PDX', 'SEA', 'ORD'] AS code CREATE (:airport {code: code});
MATCH (o:airport {code: 'ATL'}), (d:airport {code: 'BOS'}) CREATE (o)-[:route {rid: 101, dist: 946}]->(d);
MATCH (o:airport {code: 'ATL'}), (d:airport {code: 'BOS'}) CREATE (o)-[:route {rid: 102, dist: 946}]->(d);
MATCH (o:airport {code: 'ATL'}), (d:airport {code: 'LAX'}) CREATE (o)-[:route {rid: 103, dist: 1946}]->(d);
MATCH (o:airport {code: 'ATL'}), (d:airport {code: 'PDX'}) CREATE (o)-[:route {rid: 104, dist: 2172}]->(d);
MATCH (o:airport {code: 'ATL'}), (d:airport {code: 'SEA'}) CREATE (o)-[:route {rid: 105}]->(d);
