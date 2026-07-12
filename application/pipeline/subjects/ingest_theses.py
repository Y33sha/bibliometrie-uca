"""Ingestion des sujets theses.fr.

`topics = {"discipline": str, "rameau": [str, ...]}` (selon présence), libellés FR. La discipline est un libellé unique ; `rameau` liste des libellés indexés RAMEAU.
"""

from sqlalchemy import Connection

from application.pipeline.subjects._common import SubjectCache, dedup_strs
from domain.types import JsonValue

SOURCE = "theses"


def ingest(
    conn: Connection,
    *,
    publication_id: int,
    topics: JsonValue,
    cache: SubjectCache,
) -> int:
    if not isinstance(topics, dict):
        return 0
    links: list[tuple[int, int]] = []
    discipline = topics.get("discipline")
    if isinstance(discipline, str) and discipline.strip():
        sid = cache.get_or_upsert(conn, label=discipline.strip(), language="fr")
        links.append((publication_id, sid))
    for label in dedup_strs(topics.get("rameau")):
        sid = cache.get_or_upsert(conn, label=label, language="fr")
        links.append((publication_id, sid))
    return cache.link_bulk(conn, source=SOURCE, rows=links)
