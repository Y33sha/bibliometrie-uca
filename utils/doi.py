"""Utilitaires de nettoyage et validation de DOI.

Shim de compatibilité : la logique de normalisation vit désormais dans
`domain.identifiers`. `clean_doi` reste disponible pour le code existant
qui travaille sur des chaînes brutes (~50 sites d'appel dans pipeline
et extraction).

Nouveau code : préférer `DOI.try_parse(...)` (renvoie un value object)
ou `DOI(...)` (strict, lève ValidationError).
"""

from domain.identifiers import _normalize_doi


def clean_doi(doi: str | None) -> str | None:
    """Nettoie un DOI brut : supprime le préfixe URL, trim les espaces,
    et normalise les DOI versionnés (ex. .v1) vers le DOI concept.

    Gère les préfixes courants : https://doi.org/, http://doi.org/,
    https://dx.doi.org/.
    """
    return _normalize_doi(doi)
