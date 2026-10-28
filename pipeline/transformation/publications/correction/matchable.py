"""Phase `metadata_correction` — sous-étape **matchable** : calcule `source_records.is_matchable` (`is_matchable`), après les sous-étapes qui corrigent le DOI, les identifiants et les liens. Un changement de valeur marque l'enregistrement source pour la réconciliation."""

import logging
import time
from collections.abc import Set
from dataclasses import dataclass

from sqlalchemy import Connection

from domain.publications.scope import is_matchable
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, inflect, quantity, step
from pipeline.transformation.publications.correction.correction_batches import persist_in_batches
from pipeline.transformation.publications.correction.correction_store import (
    MatchabilityRow,
    MatchabilityUpdate,
    SourceRecordCorrectionStore,
)


def compute_updates(
    rows: list[MatchabilityRow], missing_hal_ids: Set[str]
) -> list[MatchabilityUpdate]:
    """Mises à jour des `source_records` dont `is_matchable` change. `missing_hal_ids` : dépôts HAL introuvables dans HAL."""
    return [
        MatchabilityUpdate(row.id, matchable)
        for row in rows
        if (matchable := is_matchable(row.facts, missing_hal_ids)) != row.is_matchable
    ]


@dataclass
class MatchabilityStats:
    """Bilan de la sous-étape : `source_records` examinées, `source_records` dont `is_matchable` change, `source_records` écartées."""

    examined: int
    changed: int
    excluded: int


def run(
    conn: Connection, store: SourceRecordCorrectionStore, logger: logging.Logger
) -> MatchabilityStats:
    """Calcule et persiste `is_matchable` sur toutes les `source_records`."""
    step(logger, "Enregistrements sources écartés de la réconciliation")
    t0 = time.perf_counter()
    rows = store.fetch_matchability_rows()
    logger.info("%s%s %s", BRANCH, quantity(len(rows), "document"), inflect(len(rows), "examiné"))

    updates = compute_updates(rows, store.fetch_missing_hal_ids())
    changed = {u.id: u.is_matchable for u in updates}
    excluded = sum(1 for row in rows if not changed.get(row.id, row.is_matchable))
    logger.info("%s%s %s", BRANCH, quantity(excluded, "document"), inflect(excluded, "écarté"))
    logger.info("%s%s à mettre à jour", BRANCH, quantity(len(updates), "document"))

    persist_in_batches(conn, updates, store.persist_matchability)
    logger.info("%sTerminé en %.1fs", LAST_BRANCH, time.perf_counter() - t0)
    return MatchabilityStats(len(rows), len(updates), excluded)
