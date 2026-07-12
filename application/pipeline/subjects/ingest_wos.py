"""Ingestion des sujets WoS.

`topics = {"subjects": [...], "headings": [...]}` (selon présence), libellés EN.
"""

from sqlalchemy import Connection

from application.pipeline.subjects._common import SubjectCache, dedup_strs
from domain.types import JsonValue

SOURCE = "wos"


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
    for key in ("subjects", "headings"):
        for label in dedup_strs(topics.get(key)):
            sid = cache.get_or_upsert(conn, label=label, language="en")
            links.append((publication_id, sid))
    return cache.link_bulk(conn, source=SOURCE, rows=links)
