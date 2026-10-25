"""Correction unaire d'un enregistrement source : ses valeurs corrigées et la trace de ses corrections."""

from collections.abc import Mapping
from typing import NamedTuple

from domain.source_records.corrections import (
    UNARY_KEYS,
    CorrectionKey,
    hydrate_raw_view,
    other_entries,
    raw_value,
    stash_entry,
    without_values,
)
from domain.source_records.metadata_correction.rules import (
    MetadataCorrectionRule,
    MetadataForCorrection,
    effective_metadata,
    origin_doc_type_correction,
    strip_dissertation_keys,
)
from domain.types import JsonValue


class CorrectedSourceRecord(NamedTuple):
    """Valeurs corrigées d'un enregistrement source, et `corrections` complète : les entrées de la correction unaire recalculées, celles des autres sous-étapes gardées. Chaque champ a le nom de sa colonne de `source_records`."""

    doc_type: str | None
    oa_status: str | None
    external_ids: dict[str, JsonValue]
    corrections: dict[str, JsonValue]


def corrected_doc_type(
    facts: MetadataForCorrection, corrections: Mapping[str, JsonValue]
) -> str | None:
    """Type d'un enregistrement source après les règles de correction."""
    before = hydrate_raw_view(facts, corrections)
    corrected = effective_metadata(before).doc_type
    return corrected.value if corrected is not None else before.doc_type


def correct_source_record(
    facts: MetadataForCorrection,
    external_ids: dict[str, JsonValue],
    corrections: Mapping[str, JsonValue],
    *,
    origin_doc_type: str | None = None,
) -> CorrectedSourceRecord | None:
    """Corrige un enregistrement source depuis ses valeurs d'avant correction, que `corrections` permet de reconstruire. Rend `None` si les valeurs courantes sont déjà les valeurs corrigées.

    `facts`, `external_ids` et `corrections` sont les valeurs courantes, éventuellement corrigées par un passage précédent. `origin_doc_type` est le type corrigé du dépôt HAL dont l'enregistrement source ScanR est issu ; il prime sur son type.

    Une conflation thèse-article corrigée en article perd ses clés de thèse (`strip_dissertation_keys`). Les identifiants retirés par la sous-étape cluster restent retirés.
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

    raw_external_ids = raw_value(corrections, CorrectionKey.EXTERNAL_IDS, external_ids)
    new_external_ids = raw_external_ids
    thesis_to_article = MetadataCorrectionRule.THESIS_WITH_SERIAL_TO_ARTICLE
    if corrected.doc_type is not None and corrected.doc_type.rule == thesis_to_article:
        stripped = strip_dissertation_keys(raw_external_ids)
        if stripped != raw_external_ids:
            new_external_ids = stripped
            new_corrections[CorrectionKey.EXTERNAL_IDS] = stash_entry(
                raw_external_ids, thesis_to_article.value
            )
    new_external_ids = without_values(
        new_external_ids, new_corrections.get(CorrectionKey.REMOVED_EXTERNAL_IDS)
    )
    result = CorrectedSourceRecord(doc_type, oa_status, new_external_ids, new_corrections)
    if result == (facts.doc_type, facts.oa_status, external_ids, dict(corrections)):
        return None
    return result
