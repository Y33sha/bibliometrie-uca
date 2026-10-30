"""Correction unaire d'un enregistrement source : ses valeurs corrigées et la trace de ses corrections."""

from collections.abc import Mapping, Sequence, Set
from typing import NamedTuple

from domain.publications.identifiers import extract_hal_id_from_url
from domain.source_records.corrections import (
    UNARY_KEYS,
    CorrectionKey,
    hydrate_raw_view,
    other_entries,
    stash_entry,
)
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierType,
    with_removals,
)
from domain.source_records.metadata_correction.rules import (
    MetadataCorrectionRule,
    MetadataForCorrection,
    effective_metadata,
    is_dissertation_identifier,
    origin_doc_type_correction,
)
from domain.types import JsonValue


class CorrectedSourceRecord(NamedTuple):
    """Valeurs corrigées d'un enregistrement source. Chaque champ a le nom de sa colonne de `source_records`."""

    doc_type: str | None
    oa_status: str | None
    urls: list[str] | None
    corrections: dict[str, JsonValue]
    """Colonne `corrections` complète : entrées de la correction unaire recalculées, entrées des autres sous-étapes gardées."""


class UnaryCorrection(NamedTuple):
    """Correction unaire d'un enregistrement source : ses colonnes corrigées et ses identifiants, aux statuts recalculés."""

    columns: CorrectedSourceRecord
    identifiers: tuple[SourceIdentifier, ...]


# Règles de retrait d'identifiants de la correction unaire.
UNARY_IDENTIFIER_RULES = frozenset(
    {
        MetadataCorrectionRule.THESIS_WITH_SERIAL_TO_ARTICLE.value,
        MetadataCorrectionRule.HAL_DEPOSIT_MISSING_TO_REMOVED.value,
    }
)


def corrected_doc_type(
    facts: MetadataForCorrection, corrections: Mapping[str, JsonValue]
) -> str | None:
    """Renvoie le type d'un enregistrement source après les règles de correction."""
    before = hydrate_raw_view(facts, corrections)
    corrected = effective_metadata(before).doc_type
    return corrected.value if corrected is not None else before.doc_type


def correct_source_record(
    facts: MetadataForCorrection,
    identifiers: Sequence[SourceIdentifier],
    corrections: Mapping[str, JsonValue],
    *,
    origin_doc_type: str | None = None,
    missing_hal_ids: Set[str] = frozenset(),
) -> UnaryCorrection | None:
    """Corrige un enregistrement source depuis ses valeurs d'avant correction, reconstruites à partir de `corrections` et de ses `identifiers`. Renvoie `None` si les valeurs courantes sont déjà les valeurs corrigées.

    Une conflation thèse-article corrigée en article perd ses identifiants de thèse (`is_dissertation_identifier`). Les identifiants et les liens des dépôts de `missing_hal_ids` sont retirés.

    Args:
        facts: valeurs courantes, éventuellement corrigées par un passage précédent.
        identifiers: tous les identifiants de l'enregistrement source, avec leur statut courant.
        corrections: colonne `corrections` courante.
        origin_doc_type: type corrigé du dépôt HAL dont l'enregistrement source ScanR est issu ; il prime sur son type.
        missing_hal_ids: dépôts HAL introuvables dans HAL.
    """
    before = hydrate_raw_view(facts, corrections)
    corrected = effective_metadata(before)
    new_corrections = other_entries(corrections, UNARY_KEYS)

    doc_type = before.doc_type
    doc_type_rule: str | None = None
    if corrected.doc_type is not None and corrected.doc_type.value != before.doc_type:
        doc_type, doc_type_rule = corrected.doc_type.value, corrected.doc_type.rule.value
    if origin := origin_doc_type_correction(doc_type, origin_doc_type):
        doc_type, doc_type_rule = origin.value, origin.rule.value
    if doc_type_rule is not None:
        new_corrections[CorrectionKey.DOC_TYPE] = stash_entry(before.doc_type, doc_type_rule)

    oa_status = before.oa_status
    if corrected.oa_status is not None and corrected.oa_status.value != before.oa_status:
        oa_status = corrected.oa_status.value
        new_corrections[CorrectionKey.OA_STATUS] = stash_entry(
            before.oa_status, corrected.oa_status.rule.value
        )

    removals: dict[tuple[SourceIdentifierType, str], str] = {}
    thesis_to_article = MetadataCorrectionRule.THESIS_WITH_SERIAL_TO_ARTICLE
    if corrected.doc_type is not None and corrected.doc_type.rule == thesis_to_article:
        for identifier in identifiers:
            if is_dissertation_identifier(identifier):
                removals.setdefault(identifier.key, thesis_to_article.value)

    urls = before.urls
    cited = {i.value for i in identifiers if i.id_type is SourceIdentifierType.HAL_ID}
    if not missing_hal_ids.isdisjoint(cited):
        missing_rule = MetadataCorrectionRule.HAL_DEPOSIT_MISSING_TO_REMOVED.value
        for hal_id in cited & missing_hal_ids:
            removals.setdefault((SourceIdentifierType.HAL_ID, hal_id), missing_rule)
        kept_urls = [u for u in urls or () if extract_hal_id_from_url(u) not in missing_hal_ids]
        if len(kept_urls) != len(urls or ()):
            urls = kept_urls or None
            new_corrections[CorrectionKey.URLS] = stash_entry(before.urls, missing_rule)

    new_identifiers = with_removals(identifiers, UNARY_IDENTIFIER_RULES, removals)
    columns = CorrectedSourceRecord(doc_type, oa_status, urls, new_corrections)
    if columns == (
        facts.doc_type,
        facts.oa_status,
        facts.urls,
        dict(corrections),
    ) and new_identifiers == tuple(identifiers):
        return None
    return UnaryCorrection(columns, new_identifiers)
