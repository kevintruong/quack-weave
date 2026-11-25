"""Regenerate the browser's Ladybug seed and Parquet file from the PaperTrail CSVs."""

import argparse
import csv
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


def graph_seed(data_dir):
    with (data_dir / "papers.csv").open(encoding="utf-8", newline="") as source:
        papers = [
            f'{{id: {int(row["id"])}, title: {json.dumps(row["title"], ensure_ascii=False)}}}'
            for row in csv.DictReader(source)
        ]
    with (data_dir / "citations.csv").open(encoding="utf-8", newline="") as source:
        links = [
            f'{{source: {int(row["from"])}, target: {int(row["to"])}}}'
            for row in csv.DictReader(source)
        ]
    return f"""CREATE NODE TABLE Document(id INT64 PRIMARY KEY, title STRING);
CREATE REL TABLE LINKS_TO(FROM Document TO Document);
UNWIND [{", ".join(papers)}] AS paper
CREATE (:Document {{id: paper.id, title: paper.title}});
UNWIND [{", ".join(links)}] AS link
MATCH (source:Document), (target:Document)
WHERE source.id = link.source AND target.id = link.target
CREATE (source)-[:LINKS_TO]->(target);
CHECKPOINT;
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duckdb", default="duckdb")
    args = parser.parse_args()
    data_dir = Path(__file__).resolve().parents[1] / "data"
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        shutil.copyfile(data_dir / "papers.csv", work / "papers.csv")
        subprocess.run(
            [args.duckdb, "-batch", "-bail"],
            input="""COPY (
    SELECT id, title, venue, year, citation_count FROM read_csv(
        'papers.csv', header := true,
        columns := {'id': 'BIGINT', 'title': 'VARCHAR', 'venue': 'VARCHAR',
                    'year': 'INTEGER', 'citation_count': 'INTEGER'}
    ) ORDER BY id
) TO 'papers.parquet' (FORMAT PARQUET);
""",
            text=True,
            check=True,
            cwd=work,
        )
        shutil.copyfile(work / "papers.parquet", data_dir / "papers.parquet")
    (data_dir / "papertrail.cypher").write_text(graph_seed(data_dir), encoding="utf-8")


if __name__ == "__main__":
    main()
