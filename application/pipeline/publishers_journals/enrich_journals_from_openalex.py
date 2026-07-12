"""Sous-étape de la phase `publishers_journals` — enrichit les revues à partir de l'API OpenAlex Sources.

Champs mis à jour :
- `apc_amount`, `apc_currency` (prix catalogue DOAJ exposés par OpenAlex)
- `journal_type` (via `domain.journals.journal.map_openalex_source_type`), uniquement quand le mapping renvoie une valeur exploitable

Le fetch OpenAlex et le circuit-breaker de source sont injectés (le HTTP vit dans `infrastructure/sources/openalex`). L'orchestrateur ne consulte que l'état du breaker pour s'arrêter quand la source est à bout de budget. Appelé par `run_pipeline`.
"""

import logging
import time
from collections import Counter
from collections.abc import Callable

from sqlalchemy import Connection

from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.circuit_breaker import CircuitBreaker
from application.ports.pipeline.enrich import EnrichQueries
from application.ports.repositories.journal_repository import (
    JournalRepository,
    JournalUpdateFields,
)
from application.services.journals.core import update_journal_apc
from domain.journals.journal import map_openalex_source_type

BATCH_SIZE = 50
COMMIT_EVERY = 500  # commit DB tous les N journals traités

FetchSourcesBatch = Callable[[list[str]], dict[str, tuple[float | None, str, str | None]]]
"""Signature du fetch injecté : `(openalex_ids) -> {short_id: (apc_amount, apc_currency, raw_type)}`."""


def run_enrich_journals_from_openalex(
    conn: Connection,
    queries: EnrichQueries,
    logger: logging.Logger,
    *,
    journal_repo: JournalRepository,
    fetch_batch: FetchSourcesBatch,
    breaker: CircuitBreaker,
    rate_delay: float = 0.1,
) -> PhaseMetrics:
    journals = queries.fetch_journals_of_unknown_type(conn, limit=None)
    total = len(journals)
    logger.info("%d revues à typer (openalex_id, journal_type inconnu).", total)
    if total == 0:
        logger.info("Rien à faire.")
        return PhaseMetrics()

    updated = 0
    with_apc = 0
    processed = 0
    type_written = 0
    raw_type_counter: Counter[str] = Counter()

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
            if raw_type:
                raw_type_counter[raw_type] += 1

            update_journal_apc(
                journal_id, apc_amount=apc_amount, apc_currency=apc_currency, repo=journal_repo
            )
            # journal_type : seules les revues `unknown` sont traitées (cf. `fetch_journals_of_unknown_type`). On écrit dès que le mapping OpenAlex renvoie une valeur ; une revue au type `metadata`/`other` reste `unknown` et repasse au prochain run.
            mapped_type = map_openalex_source_type(raw_type)
            if mapped_type is not None:
                journal_repo.update_journal_fields(
                    journal_id, JournalUpdateFields(journal_type=mapped_type)
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
    if raw_type_counter:
        distrib = ", ".join(f"{t}={n}" for t, n in raw_type_counter.most_common())
        logger.info("Distribution OpenAlex `type` : %s", distrib)
    return PhaseMetrics(seen=total, updated=updated)
