"""Phase `metadata_correction` — sous-étape unaire (corrections per-record).

Pour chaque `source_record` : reconstruit les valeurs d'avant correction (via `corrections`), puis applique les règles de correction `effective_metadata` (per-record + journal-dépendantes — les journaux sont typés à ce stade, la phase tourne après `publishers_journals`). `doc_type` arrive traduit par la normalisation dans le vocabulaire du référentiel, celui des règles. Écrit les métadonnées corrigées dans les colonnes typées et stashe la valeur d'avant correction dans `corrections`.

Idempotent et auto-cicatrisant : la correction repart toujours de la valeur d'avant correction, jamais de la valeur déjà corrigée. Un re-normalize qui réécrit la valeur, ou un changement de `journal_type` qui (dé)clenche une règle, est rattrapé au run suivant sans état à entretenir.

Les sous-étapes de la phase écrivent `corrections` sur des clés disjointes (unaire : `doc_type`/`oa_status`/`external_ids` ; cluster : `doi`/`removed_external_ids` ; `journal_by_doi` : `journal_id`) ; chaque passe préserve donc les clés qu'elle ne gère pas. La sous-étape unaire réapplique aux identifiants externes le retrait noté par la sous-étape cluster.
"""

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import Connection

from domain.source_records.corrections import (
    CORRECTED_BY,
    hydrate_raw_view,
    raw_value,
    stash_entry,
    without_values,
)
from domain.source_records.metadata_correction.rules import (
    MetadataCorrectionRule,
    effective_metadata,
    origin_doc_type_correction,
    strip_dissertation_keys,
)
from domain.source_records.metadata_correction.shared_doi import REMOVED_EXTERNAL_IDS
from domain.sources.scanr import extract_hal_id_from_scanr_id
from pipeline.runtime.observability.libelles import BRANCHE, DERNIERE_BRANCHE, accord, etape, forme
from pipeline.transformation.publications.correction.correction_batches import persist_in_batches
from pipeline.transformation.publications.correction.metadata_correction_queries import (
    CorrectionUpdate,
    PgMetadataCorrectionQueries,
    UnaryCorrectionRow,
)

# Champs corrigeables gérés par la sous-étape unaire (clés de `corrections` qu'elle (re)pose).
# Les autres (`doi` et `removed_external_ids`, gérés par la sous-étape cluster ; `journal_id`, par la sous-étape `journal_by_doi`) sont préservées.
_UNARY_FIELDS = ("doc_type", "oa_status", "external_ids")


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
        origin_doc_type = corrected_doc_type(origin) if origin else None
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


def corrected_doc_type(row: UnaryCorrectionRow) -> str | None:
    """Type corrigé d'une `source_record` par les règles de correction."""
    raw = hydrate_raw_view(row.facts, row.corrections)
    corrected = effective_metadata(raw)
    return corrected.doc_type.value if corrected.doc_type is not None else raw.doc_type


def compute_update(
    row: UnaryCorrectionRow,
    origin_doc_type: str | None = None,
) -> CorrectionUpdate | None:
    """Recalcule les métadonnées corrigées d'une `source_record` depuis ses valeurs d'avant correction. Retourne la mise à jour à persister, ou `None` si rien ne change (colonnes + `corrections` identiques).

    Le `raw` stashé est la valeur d'avant correction ; `corrected_by` nomme la règle.

    `origin_doc_type` : type corrigé du dépôt HAL dont l'enregistrement source ScanR est issu, qui prime sur le sien.

    Pure : ne fait pas d'I/O. Préserve les clés de `corrections` hors `_UNARY_FIELDS` (la sous-étape cluster gère `doi`, la sous-étape `journal_by_doi` gère `journal_id`)."""
    raw = hydrate_raw_view(row.facts, row.corrections)
    corrected = effective_metadata(raw)

    new_doc_type = raw.doc_type
    doc_type_by: str | None = None
    if corrected.doc_type is not None and corrected.doc_type.value != raw.doc_type:
        new_doc_type = corrected.doc_type.value
        doc_type_by = corrected.doc_type.rule.value
    if origin := origin_doc_type_correction(new_doc_type, origin_doc_type):
        new_doc_type = origin.value
        doc_type_by = origin.rule.value

    new_oa_status = raw.oa_status

    # external_ids : déconfliction des clés-thèse quand la correction thèse→article a firé (conflation). On repart du brut reconstruit, donc auto-cicatrisant.
    raw_external_ids = raw_value(row.corrections, "external_ids", row.external_ids)
    new_external_ids = raw_external_ids
    thesis_to_article = (
        corrected.doc_type is not None
        and corrected.doc_type.rule == MetadataCorrectionRule.THESIS_WITH_JOURNAL_TO_ARTICLE
    )

    # Repart des clés non gérées par cette sous-étape (ne pas écraser `doi` & co).
    corrections = {k: v for k, v in row.corrections.items() if k not in _UNARY_FIELDS}

    if doc_type_by is not None:
        corrections["doc_type"] = stash_entry(raw.doc_type, doc_type_by)
    if corrected.oa_status is not None and corrected.oa_status.value != raw.oa_status:
        new_oa_status = corrected.oa_status.value
        corrections["oa_status"] = stash_entry(raw.oa_status, corrected.oa_status.rule.value)
    if thesis_to_article:
        stripped = strip_dissertation_keys(raw_external_ids)
        if stripped != raw_external_ids:
            new_external_ids = stripped
            corrections["external_ids"] = stash_entry(
                raw_external_ids, MetadataCorrectionRule.THESIS_WITH_JOURNAL_TO_ARTICLE.value
            )
    # Identifiants partagés avec une autre œuvre, retirés par la sous-étape cluster.
    new_external_ids = without_values(new_external_ids, corrections.get(REMOVED_EXTERNAL_IDS))

    if (
        new_doc_type == row.facts.doc_type
        and new_oa_status == row.facts.oa_status
        and new_external_ids == row.external_ids
        and corrections == row.corrections
    ):
        return None
    return CorrectionUpdate(row.id, new_doc_type, new_oa_status, new_external_ids, corrections)


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
        for field in _UNARY_FIELDS:
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
