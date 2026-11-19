"""Tâche unaire de la phase `metadata_correction` : correction de chaque enregistrement source par `correct_source_record`, et écriture des seules mises à jour effectives.

Les revues sont typées à ce stade : la phase suit `publishing`. La correction repart des valeurs d'avant correction.
"""

import logging
import time
from collections import Counter
from collections.abc import Mapping, Set

from sqlalchemy import Connection

from domain.documents.doc_types import DocType
from domain.source_records.metadata_correction.rules import NoticeOfDoi
from domain.source_records.metadata_correction.unary import (
    correct_source_record,
    corrected_doc_type,
)
from domain.sources.registry import Source
from domain.sources.scanr import extract_hal_id_from_scanr_id
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, inflect, quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publications.correction.correction_batches import persist_in_batches
from pipeline.transformation.publications.correction.correction_store import (
    CorrectionUpdate,
    SourceRecordCorrectionStore,
    UnaryCorrectionRow,
)

_NOTICE_DOC_TYPES = frozenset({DocType.ERRATUM, DocType.RETRACTION})


def compute_updates(
    rows: list[UnaryCorrectionRow],
    hal_rows: Mapping[str, UnaryCorrectionRow],
    missing_hal_ids: Set[str],
    crossref_rows: list[UnaryCorrectionRow],
) -> list[CorrectionUpdate]:
    """Calcule les mises à jour à écrire.

    Args:
        hal_rows: enregistrements sources HAL par identifiant, parmi lesquels les dépôts d'origine des enregistrements sources ScanR.
        missing_hal_ids: dépôts introuvables dans HAL.
        crossref_rows: enregistrements sources Crossref, parmi lesquels les errata et avis aux DOI des enregistrements sources de `rows`.
    """
    notices = notices_by_doi(crossref_rows)
    updates: list[CorrectionUpdate] = []
    for row in rows:
        origin = hal_rows.get(hal_id) if (hal_id := _hal_origin_id(row)) else None
        origin_doc_type = corrected_doc_type(origin.facts, origin.corrections) if origin else None
        notice = next((n for doi in sorted(row.facts.dois) if (n := notices.get(doi))), None)
        if (update := compute_update(row, origin_doc_type, missing_hal_ids, notice)) is not None:
            updates.append(update)
    return updates


def notices_by_doi(rows: list[UnaryCorrectionRow]) -> dict[str, NoticeOfDoi]:
    """Renvoie les errata et avis de rétractation Crossref, après correction, par DOI propre."""
    notices: dict[str, NoticeOfDoi] = {}
    for row in rows:
        if row.facts.source != Source.CROSSREF:
            continue
        doc_type = corrected_doc_type(row.facts, row.corrections)
        if doc_type in _NOTICE_DOC_TYPES:
            notice = NoticeOfDoi(doc_type, row.facts.title_normalized)
            notices.update(dict.fromkeys(row.facts.dois, notice))
    return notices


def _hal_origin_id(row: UnaryCorrectionRow) -> str | None:
    """Renvoie l'identifiant du dépôt HAL d'origine d'un enregistrement source ScanR, `None` pour une autre source."""
    return extract_hal_id_from_scanr_id(row.source_id) if row.facts.source == "scanr" else None


def hal_origin_ids(rows: list[UnaryCorrectionRow]) -> list[str]:
    """Renvoie les identifiants des dépôts HAL d'origine des enregistrements sources ScanR."""
    return sorted({hal_id for row in rows if (hal_id := _hal_origin_id(row))})


def own_dois(rows: list[UnaryCorrectionRow]) -> list[str]:
    """Renvoie les DOI propres des enregistrements sources, qui désignent les errata et avis Crossref à lire."""
    return sorted({doi for row in rows for doi in row.facts.dois})


def compute_update(
    row: UnaryCorrectionRow,
    origin_doc_type: str | None = None,
    missing_hal_ids: Set[str] = frozenset(),
    notice: NoticeOfDoi | None = None,
) -> CorrectionUpdate | None:
    """Calcule la mise à jour de la correction unaire d'un enregistrement source (`correct_source_record`), ou `None` si rien ne change.

    Args:
        origin_doc_type: type corrigé du dépôt HAL d'origine d'un enregistrement source ScanR.
        notice: erratum ou avis Crossref de l'un des DOI propres de l'enregistrement source.
    """
    corrected = correct_source_record(
        row.facts,
        row.identifiers,
        row.corrections,
        origin_doc_type=origin_doc_type,
        missing_hal_ids=missing_hal_ids,
        notice=notice,
    )
    return CorrectionUpdate(row.id, corrected) if corrected is not None else None


def tally_corrections(updates: list[CorrectionUpdate]) -> dict[str, int]:
    """Compte les enregistrements sources corrigés par chaque règle (`UnaryCorrection.rules`)."""
    return Counter(rule for update in updates for rule in update.corrected.rules)


def run(conn: Connection, logger: logging.Logger) -> PhaseMetrics:
    """Corrige tous les enregistrements sources et écrit les mises à jour. Renvoie les enregistrements sources examinés, mis à jour, et le décompte par règle."""
    store = SourceRecordCorrectionStore(conn)
    t0 = time.perf_counter()
    rows = store.fetch_for_unary_correction()
    logger.info("%s%s %s", BRANCH, quantity(len(rows), "document"), inflect(len(rows), "examiné"))

    hal_rows = {row.source_id: row for row in rows if row.facts.source == "hal"}
    missing_hal_ids = store.fetch_missing_hal_ids()
    updates = compute_updates(rows, hal_rows, missing_hal_ids, rows)
    logger.info("%s%s à corriger", BRANCH, quantity(len(updates), "document"))

    written = persist_in_batches(conn, updates, store.persist_corrections)
    removed = store.delete_missing_hal_locations()
    logger.info(
        "%s%s de dépôts HAL introuvables %s",
        BRANCH,
        quantity(removed, "localisation"),
        inflect(removed, "retirée"),
    )
    logger.info("%sTerminé en %.1fs", LAST_BRANCH, time.perf_counter() - t0)
    return PhaseMetrics(seen=len(rows), updated=written, extras=tally_corrections(updates))
