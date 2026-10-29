"""Sous-étape unaire de la phase `metadata_correction` : chaque enregistrement source corrigé par `correct_source_record`, et la mise à jour écrite quand elle change quelque chose.

Les revues sont typées à ce stade : la phase suit `publishing`. La correction repart des valeurs d'avant correction : un changement de type de revue qui déclenche ou retire une règle s'applique au run suivant.
"""

import logging
import time
from collections.abc import Mapping, Set
from dataclasses import dataclass

from sqlalchemy import Connection

from domain.source_records.corrections import CORRECTED_BY, UNARY_KEYS
from domain.source_records.metadata_correction.source_record import (
    UNARY_IDENTIFIER_RULES,
    correct_source_record,
    corrected_doc_type,
)
from domain.sources.scanr import extract_hal_id_from_scanr_id
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, inflect, quantity, step
from pipeline.transformation.publications.correction.correction_batches import persist_in_batches
from pipeline.transformation.publications.correction.correction_store import (
    CorrectionUpdate,
    SourceRecordCorrectionStore,
    UnaryCorrectionRow,
)


def compute_updates(
    rows: list[UnaryCorrectionRow],
    hal_rows: Mapping[str, UnaryCorrectionRow],
    missing_hal_ids: Set[str],
) -> list[CorrectionUpdate]:
    """Mises à jour à écrire. `hal_rows` donne les enregistrements sources HAL par identifiant, où se trouvent les dépôts d'origine des enregistrements sources ScanR. `missing_hal_ids` : dépôts introuvables dans HAL."""
    updates: list[CorrectionUpdate] = []
    for row in rows:
        origin = (
            hal_rows.get(hal_id)
            if row.facts.source == "scanr"
            and (hal_id := extract_hal_id_from_scanr_id(row.source_id))
            else None
        )
        origin_doc_type = corrected_doc_type(origin.facts, origin.corrections) if origin else None
        if (update := compute_update(row, origin_doc_type, missing_hal_ids)) is not None:
            updates.append(update)
    return updates


def hal_origin_ids(rows: list[UnaryCorrectionRow]) -> list[str]:
    """Identifiants des dépôts HAL dont sont issus les enregistrements sources ScanR."""
    return sorted(
        {
            hal_id
            for row in rows
            if row.facts.source == "scanr"
            and (hal_id := extract_hal_id_from_scanr_id(row.source_id))
        }
    )


def compute_update(
    row: UnaryCorrectionRow,
    origin_doc_type: str | None = None,
    missing_hal_ids: Set[str] = frozenset(),
) -> CorrectionUpdate | None:
    """Mise à jour de la correction unaire d'un enregistrement source (`correct_source_record`), ou `None` si rien ne change. `origin_doc_type` : type corrigé du dépôt HAL dont l'enregistrement source ScanR est issu."""
    corrected = correct_source_record(
        row.facts,
        row.identifiers,
        row.corrections,
        origin_doc_type=origin_doc_type,
        missing_hal_ids=missing_hal_ids,
    )
    return CorrectionUpdate(row.id, corrected) if corrected is not None else None


@dataclass
class UnaryCorrectionStats:
    """Bilan de la passe unaire : enregistrements sources examinés, enregistrements sources corrigés par au moins une règle, déclenchements par règle."""

    examined: int
    corrected: int
    rule_counts: dict[str, int]


def tally_corrections(updates: list[CorrectionUpdate]) -> tuple[int, dict[str, int]]:
    """Nombre d'enregistrements sources corrigés et déclenchements par règle, d'après les champs unaires corrigés et les règles qui retirent des identifiants. Une règle qui corrige plusieurs champs d'un enregistrement source compte une fois."""
    rule_counts: dict[str, int] = {}
    corrected = 0
    for update in updates:
        fired = {
            i.removed_by
            for i in update.corrected.identifiers
            if i.removed_by in UNARY_IDENTIFIER_RULES
        }
        for field in UNARY_KEYS:
            entry = update.corrected.columns.corrections.get(field)
            rule = entry.get(CORRECTED_BY) if isinstance(entry, dict) else None
            if isinstance(rule, str):
                fired.add(rule)
        for rule in fired:
            rule_counts[rule] = rule_counts.get(rule, 0) + 1
        if fired:
            corrected += 1
    return corrected, rule_counts


def run(
    conn: Connection,
    store: SourceRecordCorrectionStore,
    logger: logging.Logger,
) -> UnaryCorrectionStats:
    """Corrige tous les enregistrements sources et écrit les mises à jour."""
    step(logger, "Corrections de métadonnées par document")
    t0 = time.perf_counter()
    rows = store.fetch_for_unary_correction()
    logger.info("%s%s %s", BRANCH, quantity(len(rows), "document"), inflect(len(rows), "examiné"))

    hal_rows = {row.source_id: row for row in rows if row.facts.source == "hal"}
    missing_hal_ids = store.fetch_missing_hal_ids()
    updates = compute_updates(rows, hal_rows, missing_hal_ids)
    corrected, rule_counts = tally_corrections(updates)
    logger.info("%s%s à corriger", BRANCH, quantity(corrected, "document"))

    persist_in_batches(conn, updates, store.persist_corrections)
    removed = store.delete_missing_hal_locations()
    logger.info(
        "%s%s de dépôts HAL introuvables %s",
        BRANCH,
        quantity(removed, "localisation"),
        inflect(removed, "retirée"),
    )
    logger.info("%sTerminé en %.1fs", LAST_BRANCH, time.perf_counter() - t0)
    return UnaryCorrectionStats(len(rows), corrected, rule_counts)
