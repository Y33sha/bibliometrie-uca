"""Ingestion des sujets ScanR.

`topics` : JSONB libre, soit une liste de domaines, soit un dict avec clés `domains` / `topics`. On ignore le reste.
"""

from sqlalchemy import Connection

from application.pipeline.subjects._common import SubjectCache, dedup_strs
from domain.types import JsonValue

SOURCE = "scanr"


def ingest(
    conn: Connection,
    *,
    publication_id: int,
    topics: JsonValue,
    cache: SubjectCache,
) -> int:
    links: list[tuple[int, int]] = []
    for label in _extract_domain_labels(topics):
        sid = cache.get_or_upsert(conn, label=label)
        links.append((publication_id, sid))
    return cache.link_bulk(conn, source=SOURCE, rows=links)


def _extract_domain_labels(topics: JsonValue) -> list[str]:
    """Libellés de domaine depuis la structure libre `topics`."""
    if isinstance(topics, list):
        return dedup_strs(topics)
    if isinstance(topics, dict):
        for key in ("domains", "topics"):
            v = topics.get(key)
            if isinstance(v, list):
                return dedup_strs(v)
    return []
