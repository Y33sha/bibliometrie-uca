"""Sous-étape `matchable` de la phase `metadata_correction` : calcul de `source_records.is_matchable` (`is_matchable`), après les sous-étapes de correction du DOI, des identifiants et des liens. Un changement de valeur marque l'enregistrement source pour la réconciliation."""

import logging
import time

from sqlalchemy import Connection

from domain.publications.scope import is_matchable
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, inflect, quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publications.correction.correction_batches import persist_in_batches
from pipeline.transformation.publications.correction.correction_store import (
    MatchabilityRow,
    MatchabilityUpdate,
    SourceRecordCorrectionStore,
)


def compute_updates(rows: list[MatchabilityRow]) -> list[MatchabilityUpdate]:
    """Calcule les mises à jour des enregistrements sources à valeur de `is_matchable` changée."""
    return [
        MatchabilityUpdate(row.id, matchable)
        for row in rows
        if (matchable := is_matchable(row.facts)) != row.is_matchable
    ]


def run(conn: Connection, logger: logging.Logger) -> PhaseMetrics:
    """Calcule et écrit `is_matchable` de tous les enregistrements sources. Renvoie les enregistrements sources examinés et mis à jour."""
    store = SourceRecordCorrectionStore(conn)
    t0 = time.perf_counter()
    rows = store.fetch_matchability_rows()
    logger.info("%s%s %s", BRANCH, quantity(len(rows), "document"), inflect(len(rows), "examiné"))

    updates = compute_updates(rows)
    changed = {u.id: u.is_matchable for u in updates}
    excluded = sum(1 for row in rows if not changed.get(row.id, row.is_matchable))
    logger.info("%s%s %s", BRANCH, quantity(excluded, "document"), inflect(excluded, "écarté"))
    logger.info("%s%s à mettre à jour", BRANCH, quantity(len(updates), "document"))

    written = persist_in_batches(conn, updates, store.persist_matchability)
    logger.info("%sTerminé en %.1fs", LAST_BRANCH, time.perf_counter() - t0)
    return PhaseMetrics(seen=len(rows), updated=written)
