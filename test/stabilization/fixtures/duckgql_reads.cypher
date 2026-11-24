// Ladybug versions of the small read fixtures referenced by the DuckGQL ports.
CREATE NODE TABLE Person(id INT64 PRIMARY KEY, name STRING, age INT64, missing STRING);
CREATE NODE TABLE EmptyPerson(id INT64 PRIMARY KEY, name STRING);
CREATE REL TABLE KNOWS(FROM Person TO Person, id INT64);
CREATE REL TABLE MISSING(FROM Person TO Person);
CREATE (:Person {id: 1, name: 'Ada', age: 42}),
       (:Person {id: 2, name: 'Grace', age: 35}),
       (:Person {id: 3, name: 'Ada', age: 30});
MATCH (a:Person {id: 1}), (b:Person {id: 2}) CREATE (a)-[:KNOWS {id: 1}]->(b);
MATCH (a:Person {id: 2}), (b:Person {id: 3}) CREATE (a)-[:KNOWS {id: 2}]->(b);

CREATE NODE TABLE AggregateNode(id INT64 PRIMARY KEY, name STRING, category STRING, score INT64);
CREATE REL TABLE WEIGHTED(FROM AggregateNode TO AggregateNode, id INT64, weight INT64);
CREATE (:AggregateNode {id: 1, name: 'a', category: 'A', score: 1}),
       (:AggregateNode {id: 2, name: 'b', category: 'A', score: 2}),
       (:AggregateNode {id: 3, name: 'c', category: 'B'}),
       (:AggregateNode {id: 4, name: 'd', category: 'B', score: 10});
MATCH (a:AggregateNode {id: 1}), (b:AggregateNode {id: 2})
CREATE (a)-[:WEIGHTED {id: 1, weight: 1}]->(b), (a)-[:WEIGHTED {id: 4, weight: 5}]->(b);
MATCH (a:AggregateNode {id: 2}), (b:AggregateNode {id: 3}) CREATE (a)-[:WEIGHTED {id: 2, weight: 3}]->(b);
MATCH (a:AggregateNode {id: 3}), (b:AggregateNode {id: 1}) CREATE (a)-[:WEIGHTED {id: 3, weight: 8}]->(b);
CREATE REL TABLE EXTRA(FROM AggregateNode TO AggregateNode);

CREATE NODE TABLE ChainNode(id INT64 PRIMARY KEY);
CREATE REL TABLE STEP(FROM ChainNode TO ChainNode);
CREATE REL TABLE EXIT_EDGE(FROM ChainNode TO ChainNode);
UNWIND range(1, 4) AS id CREATE (:ChainNode {id: id});
MATCH (a:ChainNode {id: 1}), (b:ChainNode {id: 2}) CREATE (a)-[:STEP]->(b), (a)-[:STEP]->(b);
MATCH (a:ChainNode {id: 2}), (b:ChainNode {id: 3}) CREATE (a)-[:STEP]->(b);
MATCH (a:ChainNode {id: 3}), (b:ChainNode {id: 1}) CREATE (a)-[:STEP]->(b);
MATCH (a:ChainNode {id: 3}), (b:ChainNode {id: 4}) CREATE (a)-[:EXIT_EDGE]->(b);

CREATE NODE TABLE PathNode(id INT64 PRIMARY KEY, name STRING);
CREATE REL TABLE HOP(FROM PathNode TO PathNode);
CREATE (:PathNode {id: 1, name: 'a'}), (:PathNode {id: 2, name: 'b'}),
       (:PathNode {id: 3, name: 'c'}), (:PathNode {id: 4, name: 'd'});
MATCH (a:PathNode {id: 1}), (b:PathNode) WHERE b.id > 1 CREATE (a)-[:HOP]->(b);
MATCH (a:PathNode {id: 2}), (b:PathNode {id: 3}) CREATE (a)-[:HOP]->(b);

CREATE NODE TABLE Sample(id INT64 PRIMARY KEY, integer_value INT64, double_value DOUBLE, text_value STRING);
CREATE (:Sample {id: 1, integer_value: 1, double_value: 2.718281828459045, text_value: 'not numeric'}),
       (:Sample {id: 2});

CREATE NODE TABLE Birthday(id INT64 PRIMARY KEY, name STRING, birthday STRING);
CREATE (:Birthday {id: 1, name: 'x', birthday: '2000-05-21'}),
       (:Birthday {id: 2, name: 'x', birthday: '2000-06-22'}),
       (:Birthday {id: 3, name: 'y', birthday: '2000-01-01'}), (:Birthday {id: 4});

CREATE NODE TABLE ReachNode(id INT64 PRIMARY KEY);
CREATE REL TABLE ARC(FROM ReachNode TO ReachNode);
UNWIND range(1, 6) AS id CREATE (:ReachNode {id: id});
UNWIND [[1, 2], [1, 2], [2, 3], [3, 4], [1, 3], [4, 1], [6, 5]] AS edge
MATCH (a:ReachNode), (b:ReachNode) WHERE a.id = edge[1] AND b.id = edge[2]
CREATE (a)-[:ARC]->(b);

CREATE NODE TABLE ReadNode(id INT64 PRIMARY KEY, score INT64);
CREATE REL TABLE READ_EDGE(FROM ReadNode TO ReadNode);
CREATE (:ReadNode {id: 1, score: 10}), (:ReadNode {id: 2, score: 20});
MATCH (a:ReadNode {id: 1}), (b:ReadNode {id: 2}) CREATE (a)-[:READ_EDGE]->(b);

CREATE NODE TABLE ComposedRoot(name STRING PRIMARY KEY);
CREATE NODE TABLE ComposedMiddle(name STRING PRIMARY KEY);
CREATE NODE TABLE ComposedLeaf(name STRING PRIMARY KEY);
CREATE REL TABLE ROOT_STEP(FROM ComposedRoot TO ComposedMiddle);
CREATE REL TABLE MIDDLE_STEP(FROM ComposedMiddle TO ComposedLeaf);
CREATE REL TABLE LEAF_STEP(FROM ComposedLeaf TO ComposedLeaf);
CREATE (:ComposedRoot {name: 'a1'}), (:ComposedMiddle {name: 'b2'}),
       (:ComposedLeaf {name: 'c3'}), (:ComposedLeaf {name: 'c4'}),
       (:ComposedLeaf {name: 'c5'}), (:ComposedLeaf {name: 'c6'});
MATCH (a:ComposedRoot), (b:ComposedMiddle) CREATE (a)-[:ROOT_STEP]->(b);
MATCH (b:ComposedMiddle), (c:ComposedLeaf) WHERE c.name IN ['c3', 'c6']
CREATE (b)-[:MIDDLE_STEP]->(c);
MATCH (a:ComposedLeaf {name: 'c3'}), (b:ComposedLeaf {name: 'c4'}), (c:ComposedLeaf {name: 'c5'})
CREATE (a)-[:LEAF_STEP]->(b), (b)-[:LEAF_STEP]->(c);
