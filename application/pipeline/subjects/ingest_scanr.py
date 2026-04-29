"""Ingestion des sujets ScanR.

Source format (cf normalize_scanr.py:176-190) :
- `keywords` : list[str] résolus depuis un dict multilingue (default/en/fr).
  La langue d'origine est perdue à la normalisation : on stocke `language=None`
  côté `subjects` (le mélange FR/EN/autre est inévitable en l'état).
- `topics`   : JSONB libre. Peut être :
  - une liste de noms de domaines (`domains` fallback) → concept `scanr_domain`.
  - une structure plus riche (libre côté ScanR) → on extrait les chaînes
    feuilles dont la nature est claire et on ignore le reste.
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
        sid = cache.get_or_upsert_free(cur, label=kw, language=None)
        links.append((publication_id, sid, None))

    for label in _extract_domain_labels(topics):
        sid = cache.get_or_upsert_concept(
            cur,
            ontology=ONTOLOGY_SCANR_DOMAIN,
            ontology_id=label.lower(),
            label=label,
        )
        links.append((publication_id, sid, None))

    return cache.link_bulk(cur, source=SOURCE, rows=links)


def _extract_domain_labels(topics: Any) -> list[str]:
    """Extrait des libellés de domaine depuis la structure libre `topics`.

    Cas observés :
    - `topics` est une liste de chaînes (`domains` fallback) → pris tel quel.
    - `topics` est un dict : on regarde les clés candidates ('domains',
      'topics') si elles contiennent des listes.
    On ignore tout le reste pour éviter de récolter du bruit.
    """
    if isinstance(topics, list):
        return dedup_strs(topics)
    if isinstance(topics, dict):
        for key in ("domains", "topics"):
            v = topics.get(key)
            if isinstance(v, list):
                return dedup_strs(v)
    return []
