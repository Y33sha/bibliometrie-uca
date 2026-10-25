"""Sidecar `corrections` : format de réversibilité des corrections de `source_records`.

Quand une correction écrit la valeur **effective** dans une colonne typée de `source_records`, la valeur d'avant correction est stashée dans la colonne JSONB `corrections`, par champ, au format :

    {"<champ>": {"raw": <valeur d'avant correction>, "corrected_by": "<règle>"}}

Ce module centralise **lecture** (reconstruction de la valeur d'avant correction) et **écriture** (stash) de ce format, de sorte que le contrat de réversibilité — `COALESCE(corrections->'<champ>'->>'raw', <colonne>)` côté SQL, `hydrate_raw_view` côté Python — soit défini en un seul endroit. Inverse des corrections (`domain/source_records/metadata_correction/`).
"""

from collections.abc import Mapping
from dataclasses import replace
from enum import StrEnum
from typing import TYPE_CHECKING, cast

from domain.types import JsonValue

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

RAW = "raw"
CORRECTED_BY = "corrected_by"


REMOVED = "removed"
BEFORE = "before"


class CorrectionKey(StrEnum):
    """Clé de `corrections`."""

    DOC_TYPE = "doc_type"
    OA_STATUS = "oa_status"
    EXTERNAL_IDS = "external_ids"
    DOI = "doi"
    REMOVED_EXTERNAL_IDS = "removed_external_ids"
    """Identifiants externes partagés avec une autre œuvre, retirés (`removal_entry`)."""
    SERIAL_ID = "serial_id"


# Clés que pose chaque sous-étape de `metadata_correction`. Chaque sous-étape réécrit les siennes et garde les autres (`other_entries`).
UNARY_KEYS = frozenset(
    {CorrectionKey.DOC_TYPE, CorrectionKey.OA_STATUS, CorrectionKey.EXTERNAL_IDS}
)
CLUSTER_KEYS = frozenset({CorrectionKey.DOI, CorrectionKey.REMOVED_EXTERNAL_IDS})
SERIAL_BY_DOI_KEYS = frozenset({CorrectionKey.SERIAL_ID})
assert UNARY_KEYS | CLUSTER_KEYS | SERIAL_BY_DOI_KEYS == set(CorrectionKey)
assert not (
    UNARY_KEYS & CLUSTER_KEYS
    or UNARY_KEYS & SERIAL_BY_DOI_KEYS
    or CLUSTER_KEYS & SERIAL_BY_DOI_KEYS
)


def other_entries(
    corrections: Mapping[str, JsonValue], owned: frozenset[CorrectionKey]
) -> dict[str, JsonValue]:
    """Entrées de `corrections` hors des clés `owned` d'une sous-étape."""
    return {k: v for k, v in corrections.items() if k not in owned}


def stash_entry(raw: JsonValue, corrected_by: str) -> dict[str, JsonValue]:
    """Entrée `corrections` pour un champ corrigé : la valeur d'avant correction + sa provenance."""
    return {RAW: raw, CORRECTED_BY: corrected_by}


def removal_entry(
    before: dict[str, JsonValue], removed: dict[str, list[str]], corrected_by: str
) -> dict[str, JsonValue]:
    """Entrée `corrections` pour des valeurs retirées d'une colonne JSONB à clés : la valeur de chaque clé touchée avant le retrait, les valeurs retirées, et la provenance."""
    return {BEFORE: before, REMOVED: dict(removed), CORRECTED_BY: corrected_by}


def without_values(mapping: dict[str, JsonValue], entry: JsonValue) -> dict[str, JsonValue]:
    """`mapping` privé des valeurs que `entry` (`removal_entry`) retire. Une clé vidée disparaît."""
    removed = entry.get(REMOVED) if isinstance(entry, dict) else None
    if not isinstance(removed, dict):
        return mapping
    result = dict(mapping)
    for key, values in removed.items():
        if not isinstance(values, list) or key not in result:
            continue
        current = result[key]
        if isinstance(current, list):
            kept = [v for v in current if v not in values]
            if kept:
                result[key] = kept
            else:
                del result[key]
        elif current in values:
            del result[key]
    return result


def with_values_restored(mapping: dict[str, JsonValue], entry: JsonValue) -> dict[str, JsonValue]:
    """`mapping` où chaque clé que `entry` (`removal_entry`) a touchée reprend sa valeur d'avant le retrait."""
    before = entry.get(BEFORE) if isinstance(entry, dict) else None
    if not isinstance(before, dict):
        return mapping
    return {**mapping, **before}


def raw_value[T](corrections: Mapping[str, JsonValue] | None, field: str, current: T) -> T:
    """Valeur d'avant correction d'un champ : la valeur stashée si la `source_record` a été corrigée sur ce champ, sinon la valeur courante de la colonne."""
    entry = corrections.get(field) if corrections else None
    if isinstance(entry, dict) and RAW in entry:
        return cast("T", entry[RAW])
    return current


def hydrate_raw_view[ViewT: DataclassInstance](
    view: ViewT,
    corrections: Mapping[str, JsonValue] | None,
) -> ViewT:
    """Reconstruit la vue aux valeurs **source d'origine** (avant correction), en réinjectant chaque champ stashé dans `corrections`. Les champs jamais corrigés gardent leur valeur courante. Inverse de la persistance des corrections.

    Générique : réinjecte tout champ présent dans `corrections` *et* sur la vue, sans liste figée — un champ corrigeable de plus est pris en charge sans modification ici.
    """
    if not corrections:
        return view
    overrides = {
        field: entry[RAW]
        for field, entry in corrections.items()
        if isinstance(entry, dict) and RAW in entry and hasattr(view, field)
    }
    return replace(view, **overrides) if overrides else view
