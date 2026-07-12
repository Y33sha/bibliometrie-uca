"""Ingestion des sujets OpenAlex (topics).

Les topics arrivent dans `topics = [{domain, field, subfield, topic}, ...]` (chaque clé un display_name). On lie la publication à chacun des niveaux présents, **à plat** : quatre concepts sans relation hiérarchique. L'extraction ne conserve pas les identifiants OpenAlex stables ; le libellé sert de clé (dédup sur `lower(label)`).
"""

from sqlalchemy import Connection

from application.pipeline.subjects._common import SubjectCache
from domain.types import JsonValue

SOURCE = "openalex"

_LEVELS = ("domain", "field", "subfield", "topic")


def ingest(
    conn: Connection,
    *,
    publication_id: int,
    topics: JsonValue,
    cache: SubjectCache,
) -> int:
    """Ingère les topics OpenAlex (les 4 niveaux, à plat). Retourne le nombre de liens créés."""
    if not isinstance(topics, list):
        return 0
    links: list[tuple[int, int]] = []
    for entry in topics:
        if not isinstance(entry, dict):
            continue
        for name in _LEVELS:
            label = entry.get(name)
            if isinstance(label, str) and label.strip():
                sid = cache.get_or_upsert(conn, label=label.strip(), language="en")
                links.append((publication_id, sid))
    return cache.link_bulk(conn, source=SOURCE, rows=links)
