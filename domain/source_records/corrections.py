"""Valeurs d'avant correction des enregistrements sources (colonne `corrections`).

Une correction écrit la valeur corrigée dans la colonne de `source_records`, et garde la valeur d'avant correction dans `corrections`, par champ :

    {"<champ>": {"raw": <valeur d'avant correction>, "corrected_by": "<règle>"}}

En SQL, la valeur d'avant correction se lit `COALESCE(corrections->'<champ>'->>'raw', <colonne>)`.
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


class CorrectionKey(StrEnum):
    """Clé de `corrections`."""

    DOC_TYPE = "doc_type"
    URLS = "urls"
    SERIAL_ID = "serial_id"


# Clés posées par chaque sous-étape de `metadata_correction`. Chaque sous-étape réécrit les siennes et garde les autres (`other_entries`).
UNARY_KEYS = frozenset(
    {
        CorrectionKey.DOC_TYPE,
        CorrectionKey.URLS,
    }
)
SERIAL_BY_DOI_KEYS = frozenset({CorrectionKey.SERIAL_ID})
assert UNARY_KEYS | SERIAL_BY_DOI_KEYS == set(CorrectionKey)
assert not UNARY_KEYS & SERIAL_BY_DOI_KEYS


def other_entries(
    corrections: Mapping[str, JsonValue], owned: frozenset[CorrectionKey]
) -> dict[str, JsonValue]:
    """Renvoie les entrées de `corrections` hors des clés `owned` d'une sous-étape."""
    return {k: v for k, v in corrections.items() if k not in owned}


def stash_entry(raw: JsonValue, corrected_by: str) -> dict[str, JsonValue]:
    """Construit l'entrée de `corrections` d'un champ corrigé : valeur d'avant correction et règle de correction."""
    return {RAW: raw, CORRECTED_BY: corrected_by}


def raw_value[T](corrections: Mapping[str, JsonValue] | None, field: str, current: T) -> T:
    """Renvoie la valeur d'avant correction d'un champ : celle de `corrections` si le champ est corrigé, sinon `current`."""
    entry = corrections.get(field) if corrections else None
    if isinstance(entry, dict) and RAW in entry:
        return cast("T", entry[RAW])
    return current


def hydrate_raw_view[ViewT: DataclassInstance](
    view: ViewT,
    corrections: Mapping[str, JsonValue] | None,
) -> ViewT:
    """Ramène la vue aux valeurs d'avant correction : chaque champ présent dans `corrections` et sur la vue reprend sa valeur d'avant correction."""
    if not corrections:
        return view
    overrides = {
        field: entry[RAW]
        for field, entry in corrections.items()
        if isinstance(entry, dict) and RAW in entry and hasattr(view, field)
    }
    return replace(view, **overrides) if overrides else view
