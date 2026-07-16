"""Sous-étape de la phase `publishers_journals` — enrichit les revues à partir de l'API OpenAlex Sources.

Champs mis à jour :
- `apc_amount`, `apc_currency` (prix catalogue DOAJ exposés par OpenAlex)
- `journal_type` (via le mapping local du `type` OpenAlex), uniquement quand le mapping renvoie une valeur exploitable

Le fetch OpenAlex et le circuit-breaker de source sont injectés (le HTTP vit dans `infrastructure/sources/openalex`). L'orchestrateur ne consulte que l'état du breaker pour s'arrêter quand la source est à bout de budget. Appelé par `run_pipeline`.
"""

import logging
import time
from collections.abc import Callable

from sqlalchemy import Connection

from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.circuit_breaker import CircuitBreaker
from application.ports.repositories.journal_repository import (
    JournalRepository,
    JournalUpdate,
)
from application.services.journals.core import update_journal_apc
from domain.journals.journal import JournalType

BATCH_SIZE = 50
COMMIT_EVERY = 500  # commit DB tous les N journals traités

_OPENALEX_SOURCE_TYPE_MAP: dict[str, JournalType] = {
    "journal": "journal",
    "repository": "repository",
    "conference": "proceedings",
    "book series": "book_series",
    "ebook platform": "ebook_platform",
}


def map_openalex_source_type(raw: str | None) -> JournalType | None:
    """Mappe le champ `type` d'une source OpenAlex vers l'enum `journal_type`, ou `None` pour les types sans signal exploitable (`metadata`, `other`) et les types inconnus.

    `preprint_server` et `media` sont absents de la table (sans équivalent dans la taxonomie OpenAlex) et restent posés à la main.
    """
    if not raw:
        return None
    return _OPENALEX_SOURCE_TYPE_MAP.get(raw.lower())


FetchSourcesBatch = Callable[[list[str]], dict[str, tuple[float | None, str, str | None]]]
"""Signature du fetch injecté : `(openalex_ids) -> {short_id: (apc_amount, apc_currency, raw_type)}`."""


def run_enrich_journals_from_openalex(
    conn: Connection,
    logger: logging.Logger,
    *,
    journal_repo: JournalRepository,
    fetch_batch: FetchSourcesBatch,
    breaker: CircuitBreaker,
    rate_delay: float = 0.1,
) -> PhaseMetrics:
    journals = journal_repo.find_journals_of_unknown_type()
    total = len(journals)
    logger.info("%d revues à typer (openalex_id, journal_type inconnu).", total)
    if total == 0:
        logger.info("Rien à faire.")
        return PhaseMetrics()

    updated = 0
    with_apc = 0
    processed = 0
    type_written = 0

    for i in range(0, total, BATCH_SIZE):
        if breaker.tripped:
            conn.commit()
            logger.warning(
                "⚡ Coupe-circuit OpenAlex : enrichissement revues interrompu à %d/%d, reste retenté au prochain run.",
                processed,
                total,
            )
            return PhaseMetrics(seen=total, updated=updated)

        id_map = {row[1]: row[0] for row in journals[i : i + BATCH_SIZE]}
        sources = fetch_batch(list(id_map))
        time.sleep(rate_delay)

        for oa_id, journal_id in id_map.items():
            data = sources.get(oa_id)
            if data is None:
                processed += 1
                continue
            apc_amount, apc_currency, raw_type = data

            update_journal_apc(
                journal_id, apc_amount=apc_amount, apc_currency=apc_currency, repo=journal_repo
            )
            # journal_type : seules les revues `unknown` sont traitées (cf. `fetch_journals_of_unknown_type`). On écrit dès que le mapping OpenAlex renvoie une valeur ; une revue au type `metadata`/`other` reste `unknown` et repasse au prochain run.
            mapped_type = map_openalex_source_type(raw_type)
            if mapped_type is not None:
                journal_repo.update_journal_fields(
                    journal_id, JournalUpdate(journal_type=mapped_type)
                )
                type_written += 1

            updated += 1
            if apc_amount is not None:
                with_apc += 1
            processed += 1

        if processed % COMMIT_EVERY < BATCH_SIZE:
            conn.commit()
        logger.info(
            "  %d/%d — %d avec APC, %d types écrits",
            min(i + BATCH_SIZE, total),
            total,
            with_apc,
            type_written,
        )

    conn.commit()
    logger.info(
        "Terminé : %d/%d revues mises à jour, %d avec APC, %d journal_type écrits.",
        updated,
        total,
        with_apc,
        type_written,
    )
    return PhaseMetrics(seen=total, updated=updated)
