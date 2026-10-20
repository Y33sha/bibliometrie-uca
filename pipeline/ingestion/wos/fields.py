"""Identité d'un record WoS : UID et DOI."""

from __future__ import annotations

from collections.abc import Mapping

from domain.publications.identifiers import clean_doi
from domain.types import JsonValue, as_mapping, as_sequence, as_str, at_path


def extract_ut(rec: Mapping[str, JsonValue]) -> str:
    """Extrait le WoS UID (ex: `WOS:000819841500009`).

    Le champ est obligatoire dans la réponse WoS — `KeyError` si absent (cas anormal qui doit remonter à l'appelant).
    """
    return as_str(rec["UID"]) or ""


def extract_doi(rec: Mapping[str, JsonValue]) -> str | None:
    """Extrait le DOI depuis les identifiants WoS, ou `None`.

    L'API WoS retourne les identifiants à un emplacement profond (`dynamic_data.cluster_related.identifiers.identifier`) et de forme polymorphique : tantôt une liste de dicts, tantôt un dict unique quand il n'y a qu'un seul identifiant. Le code tolère les deux formes et les absences à chaque niveau. Une ligne d'export tabulé de l'interface (balise `UT`) donne le DOI sous la balise `DI`.
    """
    if "UT" in rec:
        return clean_doi(as_str(rec.get("DI")))
    brut = at_path(rec, "dynamic_data", "cluster_related", "identifiers").get("identifier")
    identifiers = [brut] if isinstance(brut, Mapping) else as_sequence(brut)
    for entree in identifiers:
        ident = as_mapping(entree)
        if as_str(ident.get("type")) == "doi":
            val = ident.get("value")
            return clean_doi(str(val)) if val is not None else None
    return None
