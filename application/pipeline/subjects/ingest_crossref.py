"""Ingestion des sujets CrossRef.

Source format (cf normalize_crossref.py:140-146) :
- `keywords` : list[str] (champ `subject` de CrossRef), libres EN. Souvent
  très génériques ('Computer Science', 'Medicine'…). On les ingère malgré tout —
  un seuil de bruit pourra être ajouté plus tard si besoin.
- `topics`   : pas extrait par CrossRef en l'état (Phase 3 du chantier).
"""

from typing import Any

from application.pipeline.subjects._common import SubjectCache, dedup_strs

SOURCE = "crossref"


def ingest(
    cur: Any,
    *,
    publication_id: int,
    keywords: list[str] | None,
    topics: Any,  # noqa: ARG001 — pas exploité tant que Phase 3 n'a pas tranché
    cache: SubjectCache,
) -> int:
    links: list[tuple[int, int, float | None]] = []
    for kw in dedup_strs(keywords):
        sid = cache.get_or_upsert(cur, label=kw)
        links.append((publication_id, sid, None))
    return cache.link_bulk(cur, source=SOURCE, rows=links)
