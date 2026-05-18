"""Pure functions de parsing pour l'extraction WoS.

Vit à côté de `extract_wos.py` (wiring HTTP) et `fetch_missing_doi.py`
(adapter async). Mutualise les helpers de parsing qui étaient
dupliqués entre ces deux fichiers (`extract_ut`, `extract_doi`).

Ne fait aucun I/O.
"""

from __future__ import annotations

import re


def build_query(year: int, affiliations: list[str]) -> str:
    """Construit la requête WoS Advanced Search pour une année donnée.

    Filtre `OG=(...)` (Organization-Enhanced, OR sur les variantes
    d'affiliation) et `PY=<year>`. `affiliations` doit être non vide :
    sans organisations, l'API WoS répond 400 Bad Request sur `OG=()`.
    """
    if not affiliations:
        raise ValueError("build_query: affiliations vide (la requête WoS exige au moins une org)")
    orgs = " OR ".join(affiliations)
    return f"OG=({orgs}) AND PY=({year})"


def extract_ut(rec: dict) -> str:
    """Extrait le WoS UID (ex: `WOS:000819841500009`).

    Le champ est obligatoire dans la réponse WoS — `KeyError` si absent
    (cas anormal qui doit remonter à l'appelant).
    """
    return rec["UID"]


def get_records(data: dict) -> list[dict]:
    """Extrait la liste de records depuis la réponse API WoS.

    Chemin profond `data.Data.Records.records.REC`. Retourne `[]` si
    n'importe quel niveau manque (réponse mal formée ou vide).
    """
    try:
        return data["Data"]["Records"]["records"]["REC"]
    except (KeyError, TypeError):
        return []


def get_records_found(data: dict) -> int:
    """Extrait le nombre total de records trouvés depuis la réponse API WoS."""
    try:
        return data["QueryResult"]["RecordsFound"]
    except (KeyError, TypeError):
        return 0


def extract_doi(rec: dict) -> str | None:
    """Extrait le DOI depuis les identifiants WoS, ou `None`.

    L'API WoS retourne les identifiants à un emplacement profond
    (`dynamic_data.cluster_related.identifiers.identifier`) et de forme
    polymorphique : tantôt une liste de dicts, tantôt un dict unique
    quand il n'y a qu'un seul identifiant. Le code tolère les deux
    formes et les absences à chaque niveau.
    """
    try:
        identifiers = (
            rec.get("dynamic_data", {})
            .get("cluster_related", {})
            .get("identifiers", {})
            .get("identifier", [])
        )
        if isinstance(identifiers, dict):
            identifiers = [identifiers]
        if not isinstance(identifiers, list):
            return None
        for ident in identifiers:
            if isinstance(ident, dict) and ident.get("type") == "doi":
                val = ident.get("value")
                return str(val).strip() if val is not None else None
    except (KeyError, TypeError, AttributeError):
        pass
    return None


# Préfixes DOI systématiquement absents de WoS — preprints / repositories
# qui ne sont pas indexés. Filtrés côté client pour éviter les appels
# inutiles dans `fetch_missing_doi`.
_WOS_UNINDEXED_DOI_PREFIXES = ("10.48550/", "10.2139/", "10.21203/", "10.5281/zenodo")


def clean_doi_for_wos(doi: str) -> str | None:
    """Filtre / nettoie un DOI avant interrogation de WoS.

    Retourne `None` si le DOI ne peut pas être envoyé à WoS :

    - DOI tronqué après un `?` ou `&` (paramètres d'URL résiduels).
    - DOI dans `_WOS_UNINDEXED_DOI_PREFIXES` (preprints Zenodo, arXiv,
      SSRN, Research Square) — WoS ne les indexe pas.
    - DOI contenant `"` ou newline (casserait la requête WoS).

    Sinon, retourne le DOI nettoyé (préfixes URL retirés en amont via
    `infrastructure.sources.common.clean_doi` ; cette fonction se
    concentre sur les filtres spécifiques à WoS).
    """
    doi = re.split(r"[&?]", doi.strip())[0]
    if any(doi.lower().startswith(p) for p in _WOS_UNINDEXED_DOI_PREFIXES):
        return None
    if '"' in doi or "\n" in doi:
        return None
    return doi
