"""Ingestion des sujets WoS.

Source format (cf normalize_wos.py:317-339) :
- `keywords` : list[str] depuis l'API WoS, libres EN.
- `topics`   : {"subjects": [...], "headings": [...]} (selon présence).
  WoS n'expose pas d'identifiants ontologiques stables ; on utilise
  `lower(label)` comme `ontology_id`.
"""

from typing import Any

from application.pipeline.subjects._common import SubjectCache, dedup_strs
from domain.subject import ONTOLOGY_WOS_HEADING, ONTOLOGY_WOS_SUBJECT

SOURCE = "wos"


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

    if isinstance(topics, dict):
        for label in dedup_strs(topics.get("subjects")):
            sid = cache.get_or_upsert(
                cur,
                label=label,
                language="en",
                ontologies={ONTOLOGY_WOS_SUBJECT: {"codes": [label.lower()]}},
            )
            links.append((publication_id, sid, None))

        for label in dedup_strs(topics.get("headings")):
            sid = cache.get_or_upsert(
                cur,
                label=label,
                language="en",
                ontologies={ONTOLOGY_WOS_HEADING: {"codes": [label.lower()]}},
            )
            links.append((publication_id, sid, None))

    return cache.link_bulk(cur, source=SOURCE, rows=links)
