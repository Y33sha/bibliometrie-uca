"""Ingestion des sujets theses.fr.

Source format (cf normalize_theses.py:267-280) :
- `keywords` : list[str] (champ `sujets[].libelle`), libres FR.
- `topics`   : {"discipline": str, "rameau": [str, ...]} (selon présence).
  - discipline : libellé unique, traité comme concept `theses_discipline`.
  - rameau     : libellés indexés RAMEAU. Le PPN RAMEAU n'est pas exposé
    par theses.fr → on utilise `lower(label)` comme `ontology_id`.
"""

from typing import Any

from application.pipeline.subjects._common import SubjectCache, dedup_strs
from domain.subject import ONTOLOGY_RAMEAU, ONTOLOGY_THESES_DISCIPLINE

SOURCE = "theses"


def ingest(
    conn: Any,
    *,
    publication_id: int,
    keywords: list[str] | None,
    topics: Any,
    cache: SubjectCache,
) -> int:
    links: list[tuple[int, int, float | None]] = []

    for kw in dedup_strs(keywords):
        sid = cache.get_or_upsert(conn, label=kw)
        links.append((publication_id, sid, None))

    if isinstance(topics, dict):
        discipline = topics.get("discipline")
        if isinstance(discipline, str) and discipline.strip():
            label = discipline.strip()
            sid = cache.get_or_upsert(
                conn,
                label=label,
                language="fr",
                ontologies={ONTOLOGY_THESES_DISCIPLINE: {"codes": [label.lower()]}},
            )
            links.append((publication_id, sid, None))

        for label in dedup_strs(topics.get("rameau")):
            sid = cache.get_or_upsert(
                conn,
                label=label,
                language="fr",
                ontologies={ONTOLOGY_RAMEAU: {"codes": [label.lower()]}},
            )
            links.append((publication_id, sid, None))

    return cache.link_bulk(conn, source=SOURCE, rows=links)
