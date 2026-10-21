"""Sidecar `corrections` : format de réversibilité des corrections de `source_records`.

Quand une correction écrit la valeur **effective** dans une colonne typée de `source_records`, la valeur d'avant correction est stashée dans la colonne JSONB `corrections`, par champ, au format :

    {"<champ>": {"raw": <valeur d'avant correction>, "corrected_by": "<règle>"}}

Ce module centralise **lecture** (reconstruction de la valeur d'avant correction) et **écriture** (stash) de ce format, de sorte que le contrat de réversibilité — `COALESCE(corrections->'<champ>'->>'raw', <colonne>)` côté SQL, `hydrate_raw_view` côté Python — soit défini en un seul endroit. Inverse des corrections (`domain/source_records/metadata_correction/`).
"""

from dataclasses import replace
from typing import TYPE_CHECKING, cast

from domain.types import JsonValue

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

RAW = "raw"
CORRECTED_BY = "corrected_by"


REMOVED = "removed"
BEFORE = "before"


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
    if not isinstance(entry, dict) or not isinstance(entry.get(REMOVED), dict):
        return mapping
    removed = entry[REMOVED]
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
    if not isinstance(entry, dict) or not isinstance(entry.get(BEFORE), dict):
        return mapping
    return {**mapping, **entry[BEFORE]}


def raw_value[T](corrections: dict[str, JsonValue] | None, field: str, current: T) -> T:
    """Valeur d'avant correction d'un champ : la valeur stashée si la `source_record` a été corrigée sur ce champ, sinon la valeur courante de la colonne."""
    entry = corrections.get(field) if corrections else None
    if isinstance(entry, dict) and RAW in entry:
        return cast("T", entry[RAW])
    return current


def hydrate_raw_view[ViewT: DataclassInstance](
    view: ViewT,
    corrections: dict[str, JsonValue] | None,
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
