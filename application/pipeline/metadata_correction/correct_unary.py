"""Phase `metadata_correction` — sous-étape unaire (corrections per-record).

Pour chaque `source_publication` : reconstruit le brut normalisé (via
`raw_metadata`), **mappe** le `doc_type` source vers le canonique (`map_doc_type`),
puis applique les règles de correction `effective_metadata` (per-record + journal-
dépendantes — les journaux sont typés à ce stade, la phase tourne après
`publishers_journals`) sur les valeurs canoniques. Écrit l'effective **en place** dans
les colonnes typées et stashe le brut source écrasé dans `raw_metadata`.

Le mapping avant la correction est ce qui rend les règles gatées sur `doc_type`
opérantes pour toutes les sources : sans lui, une SP HAL porte `ART` (≠ `article`),
et aucune règle canonique ne matche.

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
from dataclasses import replace

from sqlalchemy import Connection

from application.ports.pipeline.metadata_correction import (
    CorrectionUpdate,
    MetadataCorrectionQueries,
    SourcePublicationForCorrection,
)
from domain.source_publications.correction import (
    MetadataCorrectionRule,
    effective_metadata,
    strip_dissertation_keys,
)
from domain.source_publications.doc_types import map_doc_type
from domain.source_publications.raw_metadata import hydrate_raw_view, raw_value, stash_entry
from domain.source_publications.views import SourcePublicationWithJournalView

# Champs corrigeables gérés par la sous-étape unaire (clés de `raw_metadata` qu'elle (re)pose).
# Les autres (ex. `doi`, géré par la sous-étape relationnelle) sont préservées.
_UNARY_FIELDS = ("doc_type", "journal_id", "oa_status", "external_ids")

# Provenance inscrite dans `raw_metadata.<champ>.corrected_by` quand seul le mapping
# source→canonique a changé la valeur (aucune règle de correction n'a firé).
DOC_TYPE_MAP_MARKER = "DOC_TYPE_MAP"

_PERSIST_BATCH = 5000


def _view_from_row(row: SourcePublicationForCorrection) -> SourcePublicationWithJournalView:
    """Adapte la projection `SourcePublicationForCorrection` en `SourcePublicationWithJournalView`,
    aux valeurs **courantes** des colonnes (potentiellement déjà corrigées). `hydrate_raw_view`
    reconstruit ensuite le brut source à partir de `raw_metadata`."""
    return SourcePublicationWithJournalView(
        id=row.id,
        source=row.source,
        source_id=row.source_id,
        title=row.title,
        pub_year=row.pub_year,
        doc_type=row.doc_type,
        doi=row.doi,
        journal_id=row.journal_id,
        container_title=row.container_title,
        language=row.language,
        oa_status=row.oa_status,
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

    `doc_type` subit deux transformations enchaînées : **mapping** source→canonique
    (`map_doc_type`) puis **correction** (`effective_metadata`, dont les whitelists sont
    canoniques). `journal_id`/`oa_status` n'ont que la correction (pas de mapping). Le
    `raw` stashé est toujours la valeur **source d'origine** ; `corrected_by` porte la
    règle, ou `DOC_TYPE_MAP` quand seul le mapping a changé la valeur.

    Pure : ne fait pas d'I/O. Préserve les clés de `raw_metadata` hors `_UNARY_FIELDS`
    (la sous-étape relationnelle gère `doi`)."""
    raw = hydrate_raw_view(_view_from_row(row), row.raw_metadata)

    # doc_type : mapping d'abord (None laissé tel quel — pas de représentation à traduire),
    # puis correction sur la valeur canonique.
    raw_doc_type = raw.doc_type
    mapped_doc_type = map_doc_type(raw_doc_type, row.source) if raw_doc_type is not None else None
    corrected = effective_metadata(replace(raw, doc_type=mapped_doc_type))

    new_doc_type = mapped_doc_type
    doc_type_by: str | None = None
    if corrected.doc_type is not None and corrected.doc_type.value != mapped_doc_type:
        new_doc_type = corrected.doc_type.value
        doc_type_by = corrected.doc_type.rule.value
    elif mapped_doc_type != raw_doc_type:
        doc_type_by = DOC_TYPE_MAP_MARKER

    new_journal_id = raw.journal_id
    new_oa_status = raw.oa_status

    # external_ids : déconfliction des clés-thèse quand la correction thèse→article a firé
    # (conflation). On repart du brut reconstruit, donc auto-cicatrisant.
    raw_external_ids = raw_value(row.raw_metadata, "external_ids", row.external_ids)
    new_external_ids = raw_external_ids
    thesis_to_article = (
        corrected.doc_type is not None
        and corrected.doc_type.rule == MetadataCorrectionRule.THESIS_WITH_JOURNAL_TO_ARTICLE
    )

    # Repart des clés non gérées par cette sous-étape (ne pas écraser `doi` & co).
    raw_metadata = {k: v for k, v in row.raw_metadata.items() if k not in _UNARY_FIELDS}

    if doc_type_by is not None:
        raw_metadata["doc_type"] = stash_entry(raw_doc_type, doc_type_by)
    if corrected.journal_id is not None and corrected.journal_id.value != raw.journal_id:
        new_journal_id = corrected.journal_id.value
        raw_metadata["journal_id"] = stash_entry(raw.journal_id, corrected.journal_id.rule.value)
    if corrected.oa_status is not None and corrected.oa_status.value != raw.oa_status:
        new_oa_status = corrected.oa_status.value
        raw_metadata["oa_status"] = stash_entry(raw.oa_status, corrected.oa_status.rule.value)
    if thesis_to_article:
        stripped = strip_dissertation_keys(raw_external_ids)
        if stripped != raw_external_ids:
            new_external_ids = stripped
            raw_metadata["external_ids"] = stash_entry(
                raw_external_ids, MetadataCorrectionRule.THESIS_WITH_JOURNAL_TO_ARTICLE.value
            )

    if (
        new_doc_type == row.doc_type
        and new_journal_id == row.journal_id
        and new_oa_status == row.oa_status
        and new_external_ids == row.external_ids
        and raw_metadata == row.raw_metadata
    ):
        return None
    return CorrectionUpdate(
        row.id, new_doc_type, new_journal_id, new_oa_status, new_external_ids, raw_metadata
    )


def correct_for_journal(
    conn: Connection, queries: MetadataCorrectionQueries, journal_id: int
) -> int:
    """Recompute+persiste les corrections unaires des `source_publications` d'un journal,
    après un changement de son `journal_type` (hook admin). Retourne le nombre de SP corrigées.

    À enchaîner avec `refresh_from_sources` des publications du journal côté caller : la
    colonne SP rafraîchie ici est ce que le refresh (et plus tard le matcher) liront —
    sans ce recompute, `refresh_from_sources` repartirait de la correction périmée."""
    rows = queries.fetch_for_unary_correction_by_journal(conn, journal_id)
    updates = [u for row in rows if (u := compute_update(row)) is not None]
    return queries.persist_corrections(conn, updates)


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
    logger.info("  %d corrections à appliquer", len(updates))

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
