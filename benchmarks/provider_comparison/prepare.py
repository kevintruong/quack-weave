"""Build matched, indexed LSQB message–creator projections from the pinned Ladybug SF1 file."""
import argparse
from itertools import groupby
import csv as std_csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import ladybug
import pyarrow.compute as pc
import pyarrow.csv as csv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lsqb_sf1"))
from watchlist import GRAPH_SHA, PATTERN, ROOT, digest, sql_literal

BUILD = ROOT / "build/perf/provider-comparison"
SOURCE = ROOT / "build/perf/lsqb-sf1/sf1.lbdb"


def load_relate(edges, target):
    from relate import Database
    query = ("UNWIND $groups AS g CREATE (p:Person {PersonId:g[0]}) "
             "WITH p,g UNWIND g[1] AS mid "
             "CREATE (:Message {MessageId:mid})-[:Message_hasCreator_Person]->(p)")
    db = Database(str(target))
    try:
        with edges.open(newline="") as stream:
            groups, count = [], 0
            for author, rows in groupby(std_csv.DictReader(stream), key=lambda row: int(row["author"])):
                messages = [int(row["mid"]) for row in rows]
                groups.append([author, messages])
                count += len(messages)
                if count >= 4000:
                    db.execute(query, {"groups": groups})
                    groups, count = [], 0
            if groups:
                db.execute(query, {"groups": groups})
        db.execute("CREATE RANGE INDEX author_key FOR (p:Person) ON (p.PersonId)")
        db.execute("CREATE RANGE INDEX message_key FOR (m:Message) ON (m.MessageId)")
    finally:
        db.close()


def prepare(source, destination, modulus, loader):
    if modulus < 1:
        raise ValueError("The message-ID sampling modulus must be positive")
    if digest(source) != GRAPH_SHA:
        raise ValueError("Expected the pinned LSQB SF1 source database")
    target = destination / f"mod{modulus}"
    if target.exists():
        raise FileExistsError(f"Fixture already exists: {target}")
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination) as temp:
        folder = Path(temp)
        query = (f"MATCH {PATTERN} WHERE m.MessageId % {modulus} = 0 "
                 "RETURN p.PersonId AS author, m.MessageId AS mid ORDER BY author, mid")
        with ladybug.Database(str(source), read_only=True) as db, ladybug.Connection(db) as conn:
            with conn.execute(query) as result:
                pairs = result.get_as_arrow()
        if not len(pairs) or pc.count_distinct(pairs["mid"]).as_py() != len(pairs):
            raise ValueError("Expected one edge for each distinct message")
        if any(column.null_count for column in pairs.columns):
            raise ValueError("Expected non-null endpoint IDs")
        people = pairs.select(["author"]).group_by("author").aggregate([])
        def write(name, table):
            file = folder / name
            with file.open("wb") as sink:
                sink.write((",".join(table.column_names) + "\n").encode())
                csv.write_csv(table, sink, write_options=csv.WriteOptions(include_header=False))
            return sql_literal(file)
        write("edges.csv", pairs)
        people_csv = write("people.csv", people)
        messages_csv = write("messages.csv", pairs.select(["mid"]))
        reversed_csv = write("endpoints.csv", pairs.select(["mid", "author"]))
        with ladybug.Database(str(folder / "social.lbdb")) as db, ladybug.Connection(db) as conn:
            for stmt in [
                "CREATE NODE TABLE Person(PersonId INT64, PRIMARY KEY(PersonId))",
                "CREATE NODE TABLE Message(MessageId INT64, PRIMARY KEY(MessageId))",
                "CREATE REL TABLE Message_hasCreator_Person(FROM Message TO Person)",
                f"COPY Person FROM {people_csv} (HEADER=true)",
                f"COPY Message FROM {messages_csv} (HEADER=true)",
                f"COPY Message_hasCreator_Person FROM {reversed_csv} (HEADER=true)",
                "CHECKPOINT",
            ]:
                conn.execute(stmt).close()
        del pairs, people
        if loader is None:
            load_relate(folder / "edges.csv", folder / "social.rl")
        else:
            subprocess.run([loader, folder / "edges.csv", folder / "social.rl"], check=True)
        info = {"source_sha256": GRAPH_SHA, "selection": query, "modulus": modulus,
                "files": {name: {"sha256": digest(folder / name), "bytes": (folder / name).stat().st_size}
                          for name in ["edges.csv", "social.lbdb", "social.rl"]}}
        (folder / "fixture.json").write_text(json.dumps(info, indent=2) + "\n")
        staged = folder / "finished"
        staged.mkdir()
        for name in [*info["files"], "fixture.json"]:
            (folder / name).rename(staged / name)
        staged.rename(target)
        print(target, flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", default=SOURCE, type=Path)
    p.add_argument("--destination", default=BUILD, type=Path)
    p.add_argument("--loader", type=Path, help="Optional legacy native fixture loader")
    p.add_argument("--modulus", type=int, required=True)
    a = p.parse_args()
    prepare(a.source.resolve(), a.destination.resolve(), a.modulus, a.loader.resolve() if a.loader else None)
