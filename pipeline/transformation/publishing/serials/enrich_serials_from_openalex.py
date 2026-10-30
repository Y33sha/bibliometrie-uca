"""Sous-étape de la phase `publishing` : typage des revues de type inconnu, d'après le type de leur source OpenAlex.

Les requêtes à OpenAlex sont injectées (`pipeline/ingestion/openalex`). La sous-étape s'arrête quand le circuit-breaker de la source coupe.
"""

import logging
from collections.abc import Callable

from sqlalchemy import Connection, select

from domain.serials.serial import SerialType
from infrastructure.db.tables import serials
from pipeline.http.circuit_breaker import source_tripped
from pipeline.runtime.observability.log_format import inflect
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing.serials.store import SerialStore

LABEL = "Type des publications en série sur OpenAlex"
"""Libellé de la sous-étape dans le journal de la phase."""

BATCH_SIZE = 50
COMMIT_EVERY = 500  # revues traitées par commit


def find_serials_of_unknown_type(
    conn: Connection, *, limit: int | None = None
) -> list[tuple[int, str]]:
    """Renvoie `(id, openalex_id)` des revues de type inconnu à `openalex_id`, au plus `limit` revues."""
    rows = conn.execute(
        select(serials.c.id, serials.c.openalex_id)
        .where(serials.c.openalex_id.is_not(None))
        .where(serials.c.serial_type == "unknown")
        .order_by(serials.c.id)
        .limit(limit or None)
    ).all()
    return [(r.id, r.openalex_id) for r in rows]


_OPENALEX_SOURCE_TYPE_MAP: dict[str, SerialType] = {
    "journal": SerialType.JOURNAL,
    "repository": SerialType.REPOSITORY,
    "conference": SerialType.PROCEEDINGS,
    "book series": SerialType.BOOK_SERIES,
}


def map_openalex_source_type(raw: str | None) -> SerialType | None:
    """Renvoie le `serial_type` du `type` d'une source OpenAlex, ou `None` pour un type sans équivalent : `metadata`, `other`, `ebook platform`, type inconnu. `preprint_server` et `media` se posent à la main."""
    if not raw:
        return None
    return _OPENALEX_SOURCE_TYPE_MAP.get(raw.lower())


FetchSourcesBatch = Callable[[list[str]], dict[str, str | None]]
"""Requête injectée : type brut de chaque source OpenAlex, par identifiant court."""


def run_enrich_serials_from_openalex(
    conn: Connection,
    logger: logging.Logger,
    *,
    fetch_batch: FetchSourcesBatch,
) -> PhaseMetrics:
    store = SerialStore(conn)
    pending = find_serials_of_unknown_type(conn)
    total = len(pending)
    if total == 0:
        return PhaseMetrics()

    updated = 0
    processed = 0
    type_written = 0

    for i in range(0, total, BATCH_SIZE):
        if source_tripped():
            conn.commit()
            logger.warning(
                "⚡ Coupe-circuit OpenAlex : enrichissement revues interrompu à %d/%d, reste retenté au prochain run.",
                processed,
                total,
            )
            return _summary(total, updated)

        id_map = {row[1]: row[0] for row in pending[i : i + BATCH_SIZE]}
        sources = fetch_batch(list(id_map))

        for oa_id, serial_id in id_map.items():
            if oa_id not in sources:
                processed += 1
                continue
            raw_type = sources[oa_id]
            # Une revue au type OpenAlex sans équivalent reste `unknown`, et repasse au run suivant.
            mapped_type = map_openalex_source_type(raw_type)
            if mapped_type is not None:
                store.set_serial_type(serial_id, mapped_type)
                type_written += 1

            updated += 1
            processed += 1

        if processed % COMMIT_EVERY < BATCH_SIZE:
            conn.commit()

    conn.commit()
    return _summary(total, updated)


def _summary(total: int, updated: int) -> PhaseMetrics:
    metrics = PhaseMetrics(seen=total, updated=updated)
    metrics.report = (
        f"{updated}/{total} {inflect(total, 'revue mise à jour', 'revues mises à jour')}"
    )
    return metrics
