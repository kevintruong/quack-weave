"""CM-LDBC joins adapted to the matched SF1 creator projection."""

from collections import Counter, defaultdict
import csv


REVISION = "ec0e5ab51e2b7899e8048ced8efe33992f06d394"
HOST_THRESHOLD = 128  # Keep DuckDB's offer threshold above QuackWeave's 64-key cap.
CHECKSUM_MOD = 1_000_003


def statements(graph):
    """Generate the queries shared by the tracker and the workload SQLLogic runner."""
    people = "JOIN micro_people AS p USING (author)"
    messages = "JOIN micro_messages AS m USING (mid)"
    aggregates = f"count(*) AS matches, sum(g.mid % {CHECKSUM_MOD})::BIGINT AS checksum"
    return {
        "micro_creator_selective": f"SELECT p.segment, {aggregates} FROM {graph} {people} WHERE p.tier = 1 GROUP BY p.segment",
        "micro_creator_broad": f"SELECT p.segment, {aggregates} FROM {graph} {people} GROUP BY p.segment",
        "micro_message_selective": f"SELECT m.topic, {aggregates} FROM {graph} {messages} GROUP BY m.topic",
        "micro_creator_message": f"SELECT p.segment, m.topic, {aggregates} FROM {graph} {people} {messages} "
                                 "WHERE p.tier = 1 GROUP BY p.segment, m.topic",
    }


def edge_rows(path):
    with path.open(newline="", encoding="utf-8") as source:
        rows = csv.reader(source)
        if next(rows, None) != ["author", "mid"]:
            raise ValueError("CM-LDBC requires the matched creator edge CSV")
        yield from ((int(author), int(mid)) for author, mid in rows)


def fixture_inputs(path):
    """Build two independent relation sizes, with hits, misses, duplicates and NULLs."""
    counts = Counter()
    smallest_mid = None
    for author, mid in edge_rows(path):
        counts[author] += 1
        smallest_mid = mid if smallest_mid is None else min(smallest_mid, mid)
    if len(counts) < 65:
        raise ValueError("CM-LDBC needs at least 65 distinct creator IDs")
    authors = sorted(counts, key=lambda author: (-counts[author], author))[:65]
    people = [[author, 1 if index < 4 else 2, index % 4]
              for index, author in enumerate(authors)]
    people.extend([people[0][:], [None, 1, 0], [min(counts) - 1, 1, 0]])

    mids = set()
    for author, mid in edge_rows(path):
        if author == authors[0]:
            mids.add(mid)
            if len(mids) == 16:
                break
    messages = [[mid, index % 4] for index, mid in enumerate(sorted(mids))]
    messages.extend([messages[0][:], [None, 0], [smallest_mid - 1, 0]])
    return {"people": people, "messages": messages}, sum(counts.values())


def expected_rows(edges, relations):
    """Calculate SQL bags from the canonical CSV without executing the graph queries."""
    people = defaultdict(list)
    messages = defaultdict(list)
    for author, tier, segment in relations["people"]:
        if author is not None:
            people[author].append((tier, segment))
    for mid, topic in relations["messages"]:
        if mid is not None:
            messages[mid].append(topic)

    broad, selective, posts, both = (defaultdict(lambda: [0, 0]) for _ in range(4))

    def count(groups, key, mid):
        row = groups[key]
        row[0] += 1
        row[1] += mid % CHECKSUM_MOD

    for author, mid in edges:
        topics = messages.get(mid, ())
        for topic in topics:
            count(posts, (topic,), mid)
        for tier, segment in people.get(author, ()):
            count(broad, (segment,), mid)
            if tier == 1:
                count(selective, (segment,), mid)
                for topic in topics:
                    count(both, (segment, topic), mid)
    return {name: [(*key, *result) for key, result in sorted(groups.items())] for name, groups in (
        ("micro_creator_selective", selective), ("micro_creator_broad", broad),
        ("micro_message_selective", posts), ("micro_creator_message", both),
    )}


def values_sql(rows):
    return ", ".join("(" + ", ".join("NULL" if value is None else str(value) for value in row) + ")"
                     for row in rows)


def setup(connection, relations, *, prefilter):
    connection.execute(f"SET dynamic_or_filter_threshold = {HOST_THRESHOLD}")
    connection.execute(f"SET SESSION qw_enable_runtime_watchlist = {'true' if prefilter else 'false'}")
    connection.execute("CREATE TEMP TABLE micro_people(author BIGINT, tier BIGINT, segment BIGINT)")
    connection.execute("CREATE TEMP TABLE micro_messages(mid BIGINT, topic BIGINT)")
    for table, rows in (("micro_people", relations["people"]), ("micro_messages", relations["messages"])):
        connection.execute(f"INSERT INTO {table} VALUES {values_sql(rows)}")


def sqllogic_variables(extension, graph, provider, alias, relations, expected, queries):
    from json import dumps

    def quote(value):
        return "'" + str(value).replace("'", "''") + "'"

    dims = {
        "micro_creator_selective": ("segment", "NULL::BIGINT"),
        "micro_creator_broad": ("segment", "NULL::BIGINT"),
        "micro_message_selective": ("NULL::BIGINT", "topic"),
        "micro_creator_message": ("segment", "topic"),
    }
    actual, reference = [], []
    for name, sql in queries.items():
        actual.append(f"SELECT {quote(name)}, {', '.join(dims[name])}, matches, checksum FROM ({sql}) q")
        for row in expected[name]:
            if name == "micro_message_selective":
                row = (None, *row)
            elif name != "micro_creator_message":
                row = (row[0], None, *row[1:])
            reference.append("(" + ", ".join((quote(name), *("NULL" if v is None else str(v) for v in row))) + ")")
    return {
        "QW_MICRO_EXTENSION": quote(extension.resolve()),
        "QW_MICRO_REGISTER": f"SET GLOBAL qw_{provider}_config = " + quote(dumps({"alias": alias, "path": str(graph.resolve())})),
        "QW_MICRO_THRESHOLD": HOST_THRESHOLD,
        "QW_MICRO_PEOPLE": values_sql(relations["people"]),
        "QW_MICRO_MESSAGES": values_sql(relations["messages"]),
        "QW_MICRO_RESULT": " UNION ALL ".join(actual),
        "QW_MICRO_REFERENCE": ", ".join(reference),
    }
