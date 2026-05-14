"""Ingestion des sujets CrossRef.

Source format (cf normalize_crossref.py:140-146) :
- `keywords` : list[str] (champ `subject` de CrossRef), libres EN. Souvent
  très génériques ('Computer Science', 'Medicine'…). On les ingère malgré tout —
  un seuil de bruit pourra être ajouté plus tard si besoin.
- `topics`   : pas extrait par CrossRef en l'état (cf. docs/chantiers/sujets-mots-cles.md).
"""

from sqlalchemy import Connection

from application.pipeline.subjects._common import SubjectCache, dedup_strs
from domain.json_types import JsonValue

SOURCE = "crossref"


def ingest(
    conn: Connection,
    *,
    publication_id: int,
    keywords: list[str] | None,
    topics: JsonValue,  # noqa: ARG001 — non exploité côté CrossRef (cf. docs/chantiers/sujets-mots-cles.md)
    cache: SubjectCache,
) -> int:
    links: list[tuple[int, int, float | None]] = []
    for kw in dedup_strs(keywords):
        sid = cache.get_or_upsert(conn, label=kw)
        links.append((publication_id, sid, None))
    return cache.link_bulk(conn, source=SOURCE, rows=links)
