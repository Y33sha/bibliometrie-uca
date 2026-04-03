"""Utilitaires de nettoyage et validation de DOI."""


def clean_doi(doi: str | None) -> str | None:
    """Nettoie un DOI brut : supprime le préfixe URL, trim les espaces.

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
    return doi if doi else None
