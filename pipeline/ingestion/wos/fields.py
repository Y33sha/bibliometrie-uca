"""Identifiants d'un enregistrement WoS : UID et DOI."""

from __future__ import annotations

from collections.abc import Mapping

from domain.publications.identifiers import clean_doi
from domain.types import JsonValue, as_mapping, as_sequence, as_str, at_path


def extract_ut(rec: Mapping[str, JsonValue]) -> str:
    """UID WoS d'un record de l'API (`WOS:000819841500009`). Lève `KeyError` sans UID : la réponse est anormale."""
    return as_str(rec["UID"]) or ""


def extract_doi(rec: Mapping[str, JsonValue]) -> str | None:
    """DOI d'un record WoS, ou `None`.

    L'API donne les identifiants dans `dynamic_data.cluster_related.identifiers.identifier`, en liste, ou en objet seul quand il y en a un. Une ligne d'export tabulé (balise `UT`) donne le DOI sous la balise `DI`.
    """
    if "UT" in rec:
        return clean_doi(as_str(rec.get("DI")))
    raw = at_path(rec, "dynamic_data", "cluster_related", "identifiers").get("identifier")
    identifiers = [raw] if isinstance(raw, Mapping) else as_sequence(raw)
    for entry in identifiers:
        ident = as_mapping(entry)
        if as_str(ident.get("type")) == "doi":
            val = ident.get("value")
            return clean_doi(str(val)) if val is not None else None
    return None
