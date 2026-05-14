"""Ingestion des sujets HAL.

Source format (cf normalize_hal.py:228-235) :
- `keywords` : list[str], libres, FR/EN mêlés (HAL ne distingue pas la langue).
- `topics`   : {"hal_domains": [str, ...]} ou None. HAL Solr préfixe ses
  codes par `<level>.` (ex `0.phys`, `1.phys.hexp`) pour l'auto-complétion
  par profondeur ; on strippe ce préfixe pour retrouver le code stable
  utilisé par l'API CCSD `ref/domain`. Le `label` est ensuite dérivé du
  référentiel `domain.hal_domains` : libellé feuille human-readable (ex
  "Bio-informatique" pour "info.info-bi"). Fallback sur le code si
  inconnu — résilient si HAL ajoute des domaines avant régénération.
"""

from sqlalchemy import Connection

from application.pipeline.subjects._common import SubjectCache, dedup_strs
from domain.json_types import JsonValue
from domain.sources.hal_domains import hal_domain_label
from domain.subjects.subject import ONTOLOGY_HAL_DOMAIN

SOURCE = "hal"


def _strip_level_prefix(raw: str) -> str:
    """Retire le préfixe `<digit>.` des codes domain HAL Solr.

    HAL stocke les domaines avec un préfixe de niveau (`0.phys`, `1.phys.hexp`)
    qui n'apparaît pas dans le référentiel CCSD. On l'enlève pour aligner
    sur le référentiel.
    """
    head, sep, tail = raw.partition(".")
    if sep and head.isdigit():
        return tail
    return raw


def ingest(
    conn: Connection,
    *,
    publication_id: int,
    keywords: list[str] | None,
    topics: JsonValue,
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
        sid = cache.get_or_upsert(conn, label=kw)
        links.append((publication_id, sid, None))

    if isinstance(topics, dict):
        seen_codes: set[str] = set()
        for raw in dedup_strs(topics.get("hal_domains")):
            code = _strip_level_prefix(raw)
            if code in seen_codes:
                continue
            seen_codes.add(code)
            sid = cache.get_or_upsert(
                conn,
                label=hal_domain_label(code),
                ontologies={ONTOLOGY_HAL_DOMAIN: {"codes": [code]}},
            )
            links.append((publication_id, sid, None))

    return cache.link_bulk(conn, source=SOURCE, rows=links)
