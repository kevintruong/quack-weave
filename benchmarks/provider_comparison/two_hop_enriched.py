"""Read sibling messages through the graph and enrich their path bag in DuckDB."""
from collections import Counter, defaultdict
from pathlib import Path

from micro_workloads import CHECKSUM_MOD, edge_rows, values_sql


CASE_ID = "two_hop_enriched"
SCHEMA = [["author", "BIGINT"], ["segment", "BIGINT"], ["paths", "BIGINT"], ["checksum", "BIGINT"]]
SQL = f"""SELECT g.author, a.segment, count(*) AS paths, sum(g.sibling % {CHECKSUM_MOD})::BIGINT AS checksum
FROM qw_query('social', 'cypher',
    'MATCH (s:Message)-[:Message_hasCreator_Person]->(p:Person)<-[:Message_hasCreator_Person]-(t:Message)
     WHERE s.MessageId = $seed AND t.MessageId <> s.MessageId
     RETURN p.PersonId AS author, t.MessageId AS sibling',
    schema := 'author BIGINT, sibling BIGINT', bindings := {{'seed': getvariable('two_hop_seed')}}) AS g
JOIN two_hop_attributes AS a USING (sibling)
WHERE a.active
GROUP BY g.author, a.segment
ORDER BY g.author, a.segment"""


def prepare(edges_path: Path, directory: Path):
    """Choose a stable seed and derive the expected path bag independently of the graph."""
    earliest = {}
    has_siblings = set()
    for author, mid in edge_rows(edges_path):
        first = earliest.setdefault(author, mid)
        if mid != first:
            has_siblings.add(author)
            earliest[author] = min(first, mid)
    if not has_siblings:
        raise ValueError("Two-hop enrichment requires a message with a distinct sibling")
    seed = min(earliest[author] for author in has_siblings)

    # Every creator of the seed who has siblings must have the seed as its smallest
    # message, or its smaller message would have won the global seed selection.
    creators = {author for author in has_siblings if earliest[author] == seed}
    anchors = Counter()
    siblings = Counter()
    for author, mid in edge_rows(edges_path):
        if author in creators:
            if mid == seed:
                anchors[author] += 1
            else:
                siblings[author, mid] += 1

    mids = sorted({mid for _, mid in siblings})
    attributes = [[mid, index % 2, True] for index, mid in enumerate(mids)]
    # Preserve one active duplicate and exercise inactive, self, and NULL-key rows.
    attributes.extend([attributes[0][:], [mids[0], 0, False], [seed, 0, True], [None, 0, True]])
    active_segments = defaultdict(Counter)
    for mid, segment, active in attributes:
        if active and mid is not None:
            active_segments[mid][segment] += 1

    groups = defaultdict(lambda: [0, 0])
    for (author, mid), sibling_edges in siblings.items():
        remainder = mid % CHECKSUM_MOD if mid >= 0 else -(-mid % CHECKSUM_MOD)
        for segment, attribute_rows in active_segments[mid].items():
            paths = anchors[author] * sibling_edges * attribute_rows
            group = groups[author, segment]
            group[0] += paths
            group[1] += remainder * paths
    return {"seed": seed, "attributes": attributes}, [[*key, *totals] for key, totals in sorted(groups.items())]


def setup_sql(parameters, directory: Path) -> list[str]:
    return [
        f"SET VARIABLE two_hop_seed = {parameters['seed']:d}::BIGINT",
        "CREATE TEMP TABLE two_hop_attributes(sibling BIGINT, segment BIGINT, active BOOLEAN)",
        "INSERT INTO two_hop_attributes VALUES " + values_sql(parameters["attributes"]),
    ]


def setup(cursor, parameters, directory: Path):
    for statement in setup_sql(parameters, directory):
        cursor.execute(statement)
