"""Phase `metadata_correction` — sous-étape unaire (corrections per-record).

Pour chaque `source_publication` : reconstruit le brut normalisé (via
`raw_metadata`), applique `effective_metadata` (règles per-record + journal-
dépendantes — les journaux sont typés à ce stade, la phase tourne après
`publishers_journals`), écrit l'effective **en place** dans les colonnes typées et
stashe le brut écrasé dans `raw_metadata`.

Idempotent et auto-cicatrisant : la correction repart toujours du **brut
reconstruit**, jamais de la valeur déjà corrigée. Un re-normalize qui réécrit le
brut, ou un changement de `journal_type` qui (dé)clenche une règle, est rattrapé
au run suivant sans état à entretenir.

La sous-étape **relationnelle** (corrections par cluster / group-by-DOI, nullage de
DOI) viendra en Phase 2 dans ce même package. Les deux sous-étapes écrivent
`raw_metadata` mais sur des clés disjointes (unaire : `doc_type`/`journal_id`/
`oa_status` ; cluster : `doi`) ; cette passe préserve donc les clés qu'elle ne gère
pas.
"""

import logging

from sqlalchemy import Connection

from application.ports.pipeline.metadata_correction import (
    CorrectionUpdate,
    MetadataCorrectionQueries,
    SourcePublicationForCorrection,
)
from domain.source_publications.correction import effective_metadata
from domain.source_publications.views import SourcePublicationWithJournalView

# Champs corrigeables gérés par la sous-étape unaire. Les autres clés de
# `raw_metadata` (ex. `doi`, géré par la sous-étape relationnelle) sont préservées.
_UNARY_FIELDS = ("doc_type", "journal_id", "oa_status")

_PERSIST_BATCH = 5000


def _raw(row: SourcePublicationForCorrection, field: str, current: object) -> object:
    """Valeur brute reconstruite d'un champ : `raw_metadata->'<field>'->>'raw'` si la
    SP a été corrigée sur ce champ, sinon la valeur courante de la colonne."""
    entry = row.raw_metadata.get(field)
    if isinstance(entry, dict) and "raw" in entry:
        return entry["raw"]
    return current


def _raw_view(row: SourcePublicationForCorrection) -> SourcePublicationWithJournalView:
    """Vue à valeurs **brutes** pour les champs corrigeables (les autres tels quels),
    enrichie des champs joints de `journals`. C'est l'input de `effective_metadata`."""
    return SourcePublicationWithJournalView(
        id=row.id,
        source=row.source,
        source_id=row.source_id,
        title=row.title,
        pub_year=row.pub_year,
        doc_type=_raw(row, "doc_type", row.doc_type),  # type: ignore[arg-type]
        doi=row.doi,
        journal_id=_raw(row, "journal_id", row.journal_id),  # type: ignore[arg-type]
        container_title=row.container_title,
        language=row.language,
        oa_status=_raw(row, "oa_status", row.oa_status),  # type: ignore[arg-type]
        is_retracted=None,
        abstract=None,
        countries=(),
        keywords=(),
        urls=tuple(row.urls or ()),
        topics=None,
        biblio=None,
        meta=None,
        journal_type=row.journal_type,
        oa_model=row.oa_model,
        apc_amount=row.apc_amount,
    )


def compute_update(row: SourcePublicationForCorrection) -> CorrectionUpdate | None:
    """Recalcule l'effective d'une SP depuis son brut reconstruit. Retourne la mise à
    jour à persister, ou `None` si rien ne change (colonnes + `raw_metadata` identiques).

    Pure : ne fait pas d'I/O. Préserve les clés de `raw_metadata` hors `_UNARY_FIELDS`
    (la sous-étape relationnelle gère `doi`)."""
    view = _raw_view(row)
    corrected = effective_metadata(view)

    new_doc_type = view.doc_type
    new_journal_id = view.journal_id
    new_oa_status = view.oa_status

    # Repart des clés non gérées par cette sous-étape (ne pas écraser `doi` & co).
    raw_metadata = {k: v for k, v in row.raw_metadata.items() if k not in _UNARY_FIELDS}

    if corrected.doc_type is not None and corrected.doc_type.value != view.doc_type:
        new_doc_type = corrected.doc_type.value
        raw_metadata["doc_type"] = {"raw": view.doc_type, "by": corrected.doc_type.rule.value}
    if corrected.journal_id is not None and corrected.journal_id.value != view.journal_id:
        new_journal_id = corrected.journal_id.value
        raw_metadata["journal_id"] = {
            "raw": view.journal_id,
            "by": corrected.journal_id.rule.value,
        }
    if corrected.oa_status is not None and corrected.oa_status.value != view.oa_status:
        new_oa_status = corrected.oa_status.value
        raw_metadata["oa_status"] = {"raw": view.oa_status, "by": corrected.oa_status.rule.value}

    if (
        new_doc_type == row.doc_type
        and new_journal_id == row.journal_id
        and new_oa_status == row.oa_status
        and raw_metadata == row.raw_metadata
    ):
        return None
    return CorrectionUpdate(row.id, new_doc_type, new_journal_id, new_oa_status, raw_metadata)


def run(
    conn: Connection,
    queries: MetadataCorrectionQueries,
    logger: logging.Logger,
    *,
    dry_run: bool = False,
) -> None:
    """Passe unaire : corrige et persiste l'effective sur toutes les `source_publications`."""
    rows = queries.fetch_for_unary_correction(conn)
    logger.info("metadata_correction (unaire) : %d source_publications examinées", len(rows))

    updates = [u for row in rows if (u := compute_update(row)) is not None]
    logger.info("  %d corrections à persister", len(updates))

    if dry_run:
        conn.rollback()
        logger.info("DRY-RUN : aucune écriture")
        return

    total = 0
    for start in range(0, len(updates), _PERSIST_BATCH):
        batch = updates[start : start + _PERSIST_BATCH]
        total += queries.persist_corrections(conn, batch)
        conn.commit()
    logger.info("✓ %d source_publications corrigées", total)
