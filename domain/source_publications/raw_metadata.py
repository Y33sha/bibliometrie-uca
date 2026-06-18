"""Sidecar `raw_metadata` : format de réversibilité des corrections de `source_publications`.

Quand une correction écrit la valeur **effective** dans une colonne typée de
`source_publications`, le brut source écrasé est stashé dans la colonne JSONB
`raw_metadata`, par champ, au format :

    {"<champ>": {"raw": <valeur source d'origine>, "corrected_by": "<règle ou marqueur>"}}

Ce module centralise **lecture** (reconstruction du brut) et **écriture** (stash) de
ce format, de sorte que le contrat de réversibilité — `COALESCE(raw_metadata->'<champ>'->>'raw', <colonne>)`
côté SQL, `hydrate_raw_view` côté Python — soit défini en un seul endroit. Inverse
des corrections (`domain/source_publications/correction.py`).
"""

from dataclasses import replace
from typing import TYPE_CHECKING

from domain.types import JsonValue

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

RAW = "raw"
CORRECTED_BY = "corrected_by"


def stash_entry(raw: JsonValue, corrected_by: str) -> dict[str, JsonValue]:
    """Entrée `raw_metadata` pour un champ corrigé : la valeur source + sa provenance."""
    return {RAW: raw, CORRECTED_BY: corrected_by}


def raw_value[T](raw_metadata: dict[str, JsonValue] | None, field: str, current: T) -> T:
    """Valeur source d'origine d'un champ : le brut stashé si la SP a été corrigée sur
    ce champ, sinon la valeur courante de la colonne (jamais corrigée)."""
    entry = raw_metadata.get(field) if raw_metadata else None
    if isinstance(entry, dict) and RAW in entry:
        return entry[RAW]  # type: ignore[return-value]
    return current


def hydrate_raw_view[ViewT: DataclassInstance](
    view: ViewT,
    raw_metadata: dict[str, JsonValue] | None,
) -> ViewT:
    """Reconstruit la vue aux valeurs **source d'origine** (avant correction), en
    réinjectant chaque champ stashé dans `raw_metadata`. Les champs jamais corrigés
    gardent leur valeur courante. Inverse de la persistance des corrections.

    Générique : réinjecte tout champ présent dans `raw_metadata` *et* sur la vue, sans
    liste figée — un nouveau champ corrigeable est pris en charge sans modification ici.
    """
    if not raw_metadata:
        return view
    overrides = {
        field: entry[RAW]
        for field, entry in raw_metadata.items()
        if isinstance(entry, dict) and RAW in entry and hasattr(view, field)
    }
    return replace(view, **overrides) if overrides else view
