"""Parsing pur de l'API WoS (sans I/O).

Partagé par l'adapter d'extraction (`extract_wos`) et l'adapter fetch-missing-doi (`fetch_missing_doi`) : requête Advanced Search, extraction des records / UID / DOI depuis la réponse, filtrage des DOIs non indexés par WoS. Ne dépend que du format de l'API WoS.
"""

from __future__ import annotations

from collections.abc import Mapping

from domain.publications.identifiers import clean_doi
from domain.types import JsonValue, as_int, as_mapping, as_sequence, as_str, at_path

# ── Requête WoS Advanced Search ───────────────────────────────────


def build_query(year: int, affiliations: list[str]) -> str:
    """Construit la requête WoS Advanced Search pour une année donnée.

    Filtre `OG=(...)` (Organization-Enhanced, OR sur les variantes d'affiliation) et `PY=<year>`. `affiliations` doit être non vide : sans organisations, l'API WoS répond 400 Bad Request sur `OG=()`.
    """
    if not affiliations:
        raise ValueError("build_query: affiliations vide (la requête WoS exige au moins une org)")
    orgs = " OR ".join(affiliations)
    return f"OG=({orgs}) AND PY=({year})"


# ── Parsing de records ─────────────────────────────────────────────


def extract_ut(rec: Mapping[str, JsonValue]) -> str:
    """Extrait le WoS UID (ex: `WOS:000819841500009`).

    Le champ est obligatoire dans la réponse WoS — `KeyError` si absent (cas anormal qui doit remonter à l'appelant).
    """
    return as_str(rec["UID"]) or ""


def get_records(data: Mapping[str, JsonValue]) -> list[Mapping[str, JsonValue]]:
    """Extrait la liste de records depuis la réponse API WoS.

    Chemin profond `data.Data.Records.records.REC`. Retourne `[]` si n'importe quel niveau manque (réponse mal formée ou vide).
    """
    records = at_path(data, "Data", "Records", "records").get("REC")
    return [as_mapping(r) for r in as_sequence(records)]


def get_records_found(data: Mapping[str, JsonValue]) -> int:
    """Extrait le nombre total de records trouvés depuis la réponse API WoS."""
    return as_int(as_mapping(data.get("QueryResult")).get("RecordsFound")) or 0


def extract_doi(rec: Mapping[str, JsonValue]) -> str | None:
    """Extrait le DOI depuis les identifiants WoS, ou `None`.

    L'API WoS retourne les identifiants à un emplacement profond (`dynamic_data.cluster_related.identifiers.identifier`) et de forme polymorphique : tantôt une liste de dicts, tantôt un dict unique quand il n'y a qu'un seul identifiant. Le code tolère les deux formes et les absences à chaque niveau.
    """
    brut = at_path(rec, "dynamic_data", "cluster_related", "identifiers").get("identifier")
    identifiers = [brut] if isinstance(brut, Mapping) else as_sequence(brut)
    for entree in identifiers:
        ident = as_mapping(entree)
        if as_str(ident.get("type")) == "doi":
            val = ident.get("value")
            return clean_doi(str(val)) if val is not None else None
    return None


# Préfixes DOI systématiquement absents de WoS — preprints / repositories qui ne sont pas indexés. Filtrés côté client pour éviter les appels inutiles dans `fetch_missing_doi`.
_WOS_UNINDEXED_DOI_PREFIXES = ("10.48550/", "10.2139/", "10.21203/", "10.5281/zenodo")


def filter_doi_for_wos(doi: str) -> str | None:
    """Écarte un DOI (déjà normalisé par `clean_doi`) non interrogeable sur WoS.

    Retourne `None` si :

    - le DOI est dans `_WOS_UNINDEXED_DOI_PREFIXES` (preprints Zenodo, arXiv, SSRN, Research Square) — WoS ne les indexe pas ;
    - le DOI contient `"` ou newline (casserait la requête WoS).

    Sinon retourne le DOI tel quel. La normalisation (préfixe URL, casse, encodage, suffixes) est faite en amont par `clean_doi` : ici, uniquement le filtrage propre à WoS.
    """
    if any(doi.startswith(p) for p in _WOS_UNINDEXED_DOI_PREFIXES):
        return None
    if '"' in doi or "\n" in doi:
        return None
    return doi
