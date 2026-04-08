"""Utilitaires de nettoyage et validation de DOI."""

import re

# Suffixe de version sur les DOI de dépôts de données (figshare, zenodo,
# techrxiv, opticaopen…).  On normalise vers le DOI "concept" (sans version)
# qui pointe toujours vers la dernière version.
_VERSION_SUFFIX = re.compile(r"\.v\d+$", re.IGNORECASE)


def clean_doi(doi: str | None) -> str | None:
    """Nettoie un DOI brut : supprime le préfixe URL, trim les espaces,
    et normalise les DOI versionnés (ex. .v1) vers le DOI concept.

    Gère les préfixes courants : https://doi.org/, http://doi.org/,
    https://dx.doi.org/.
    """
    if not doi:
        return None
    doi = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
            break
    doi = doi.strip()
    if not doi:
        return None
    doi = _VERSION_SUFFIX.sub("", doi)
    return doi if doi else None
