"""Phase `metadata_correction` — sous-étape unaire : chaque `source_record` corrigée par `correct_source_record`, la mise à jour persistée quand elle change quelque chose.

Les journaux sont typés à ce stade : la phase tourne après `publishers_journals`. La correction repart des valeurs d'avant correction, si bien qu'un changement de `journal_type` qui (dé)clenche une règle est rattrapé au run suivant.
"""

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import Connection

from domain.source_records.corrections import CORRECTED_BY, UNARY_KEYS
from domain.source_records.metadata_correction.source_record import (
    correct_source_record,
    corrected_doc_type,
)
from domain.sources.scanr import extract_hal_id_from_scanr_id
from pipeline.runtime.observability.libelles import BRANCHE, DERNIERE_BRANCHE, accord, etape, forme
from pipeline.transformation.publications.correction.correction_batches import persist_in_batches
from pipeline.transformation.publications.correction.metadata_correction_queries import (
    CorrectionUpdate,
    PgMetadataCorrectionQueries,
    UnaryCorrectionRow,
)


def compute_updates(
    rows: list[UnaryCorrectionRow],
    hal_rows: Mapping[str, UnaryCorrectionRow],
) -> list[CorrectionUpdate]:
    """Mises à jour à persister pour `rows`. `hal_rows` : enregistrements sources HAL par identifiant, où se trouvent les dépôts d'origine des enregistrements sources ScanR de `rows`."""
    updates: list[CorrectionUpdate] = []
    for row in rows:
        origin = (
            hal_rows.get(hal_id)
            if row.facts.source == "scanr"
            and (hal_id := extract_hal_id_from_scanr_id(row.source_id))
            else None
        )
        origin_doc_type = corrected_doc_type(origin.facts, origin.corrections) if origin else None
        if (update := compute_update(row, origin_doc_type)) is not None:
            updates.append(update)
    return updates


def hal_origin_ids(rows: list[UnaryCorrectionRow]) -> list[str]:
    """Identifiants des dépôts HAL dont sont issus les enregistrements sources ScanR de `rows`."""
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
) -> CorrectionUpdate | None:
    """Mise à jour de la correction unaire d'une `source_record` (`correct_source_record`), ou `None` si rien ne change. `origin_doc_type` : type corrigé du dépôt HAL dont l'enregistrement source ScanR est issu."""
    corrected = correct_source_record(
        row.facts, row.external_ids, row.corrections, origin_doc_type=origin_doc_type
    )
    current = (row.facts.doc_type, row.facts.oa_status, row.external_ids, row.corrections)
    if tuple(corrected) == current:
        return None
    return CorrectionUpdate(row.id, *corrected)


@dataclass
class UnaryCorrectionStats:
    """Bilan de la passe unaire : `source_records` examinées, `source_records` corrigées par au moins une règle, et nombre de déclenchements par règle."""

    examined: int
    corrected: int
    rule_counts: dict[str, int]


def tally_corrections(updates: list[CorrectionUpdate]) -> tuple[int, dict[str, int]]:
    """`(source_records corrigées, déclenchements par règle)` à partir des `corrected_by` des champs unaires."""
    rule_counts: dict[str, int] = {}
    corrected = 0
    for update in updates:
        fired = False
        for field in UNARY_KEYS:
            entry = update.corrections.get(field)
            rule = entry.get(CORRECTED_BY) if isinstance(entry, dict) else None
            if isinstance(rule, str):
                rule_counts[rule] = rule_counts.get(rule, 0) + 1
                fired = True
        if fired:
            corrected += 1
    return corrected, rule_counts


def run(
    conn: Connection,
    queries: PgMetadataCorrectionQueries,
    logger: logging.Logger,
) -> UnaryCorrectionStats:
    """Passe unaire : corrige et persiste les métadonnées corrigées sur toutes les `source_records`."""
    etape(logger, "Corrections de métadonnées par document")
    t0 = time.perf_counter()
    rows = queries.fetch_for_unary_correction(conn)
    logger.info("%s%s %s", BRANCHE, accord(len(rows), "document"), forme(len(rows), "examiné"))

    hal_rows = {row.source_id: row for row in rows if row.facts.source == "hal"}
    updates = compute_updates(rows, hal_rows)
    corrected, rule_counts = tally_corrections(updates)
    logger.info("%s%s à corriger", BRANCHE, accord(corrected, "document"))

    persist_in_batches(conn, updates, queries.persist_corrections)
    logger.info("%sTerminé en %.1fs", DERNIERE_BRANCHE, time.perf_counter() - t0)
    return UnaryCorrectionStats(len(rows), corrected, rule_counts)
