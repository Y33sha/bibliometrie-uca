"""Ingestion des sujets HAL (domaines CCSD).

Les domaines arrivent dans `topics = {"hal_domains": [str, ...]}`. HAL Solr préfixe ses codes par `<level>.` (ex `0.phys`, `1.phys.hexp`) pour l'auto-complétion par profondeur ; on strippe ce préfixe pour retrouver le code stable du référentiel CCSD, dont on dérive le libellé feuille via `domain.hal_domains` (fallback sur le code si inconnu). Le code lui-même n'est pas conservé.
"""

from sqlalchemy import Connection

from application.pipeline.subjects._common import SubjectCache, dedup_strs
from domain.sources.hal_domains import hal_domain_label
from domain.types import JsonValue

SOURCE = "hal"


def _strip_level_prefix(raw: str) -> str:
    """Retire le préfixe `<digit>.` des codes domain HAL Solr (`0.phys` → `phys`)."""
    head, sep, tail = raw.partition(".")
    if sep and head.isdigit():
        return tail
    return raw


def ingest(
    conn: Connection,
    *,
    publication_id: int,
    topics: JsonValue,
    cache: SubjectCache,
) -> int:
    """Ingère les domaines HAL d'une publication. Retourne le nombre de liens créés."""
    if not isinstance(topics, dict):
        return 0
    links: list[tuple[int, int]] = []
    seen_codes: set[str] = set()
    for raw in dedup_strs(topics.get("hal_domains")):
        code = _strip_level_prefix(raw)
        if code in seen_codes:
            continue
        seen_codes.add(code)
        sid = cache.get_or_upsert(conn, label=hal_domain_label(code))
        links.append((publication_id, sid))
    return cache.link_bulk(conn, source=SOURCE, rows=links)
