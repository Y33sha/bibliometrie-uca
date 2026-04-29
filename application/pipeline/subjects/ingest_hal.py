"""Ingestion des sujets HAL.

Source format (cf normalize_hal.py:228-235) :
- `keywords` : list[str], libres, FR/EN mêlés (HAL ne distingue pas la langue).
- `topics`   : {"hal_domains": [str, ...]} ou None.
  Les codes HAL sont stables (ex 'info.eea', 'sdv.bbm') ; on les utilise
  comme `ontology_id`. Faute de label human-readable côté Solr, on stocke
  le code lui-même comme `label` (à décorer côté UI ultérieurement).
"""

from typing import Any

from application.pipeline.subjects._common import SubjectCache, dedup_strs
from domain.subject import ONTOLOGY_HAL_DOMAIN

SOURCE = "hal"


def ingest(
    cur: Any,
    *,
    publication_id: int,
    keywords: list[str] | None,
    topics: Any,
    cache: SubjectCache,
) -> int:
    """Ingère keywords + hal_domains pour une publication HAL.
    Retourne le nombre de liens créés.

    `cache` est partagé par l'orchestrateur entre toutes les publications
    d'une même source : les sujets récurrents ne déclenchent qu'un seul
    UPSERT chacun.
    """
    links: list[tuple[int, int, float | None]] = []

    for kw in dedup_strs(keywords):
        sid = cache.get_or_upsert_free(cur, label=kw, language=None)
        links.append((publication_id, sid, None))

    if isinstance(topics, dict):
        for code in dedup_strs(topics.get("hal_domains")):
            sid = cache.get_or_upsert_concept(
                cur,
                ontology=ONTOLOGY_HAL_DOMAIN,
                ontology_id=code,
                label=code,
            )
            links.append((publication_id, sid, None))

    return cache.link_bulk(cur, source=SOURCE, rows=links)
