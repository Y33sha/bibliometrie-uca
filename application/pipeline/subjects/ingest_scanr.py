"""Ingestion des sujets ScanR.

Source format (cf normalize_scanr.py:176-190) :
- `keywords` : list[str] résolus depuis un dict multilingue (default/en/fr).
  La langue d'origine est perdue à la normalisation.
- `topics`   : JSONB libre. Peut être une liste de domaines ou une
  structure dict avec clés `domains` / `topics`. On ignore le reste.
"""

from typing import Any

from application.pipeline.subjects._common import SubjectCache, dedup_strs
from domain.subject import ONTOLOGY_SCANR_DOMAIN

SOURCE = "scanr"


def ingest(
    cur: Any,
    *,
    publication_id: int,
    keywords: list[str] | None,
    topics: Any,
    cache: SubjectCache,
) -> int:
    links: list[tuple[int, int, float | None]] = []

    for kw in dedup_strs(keywords):
        sid = cache.get_or_upsert(cur, label=kw)
        links.append((publication_id, sid, None))

    for label in _extract_domain_labels(topics):
        sid = cache.get_or_upsert(
            cur,
            label=label,
            ontologies={ONTOLOGY_SCANR_DOMAIN: {"codes": [label.lower()]}},
        )
        links.append((publication_id, sid, None))

    return cache.link_bulk(cur, source=SOURCE, rows=links)


def _extract_domain_labels(topics: Any) -> list[str]:
    """Extrait des libellés de domaine depuis la structure libre `topics`."""
    if isinstance(topics, list):
        return dedup_strs(topics)
    if isinstance(topics, dict):
        for key in ("domains", "topics"):
            v = topics.get(key)
            if isinstance(v, list):
                return dedup_strs(v)
    return []
