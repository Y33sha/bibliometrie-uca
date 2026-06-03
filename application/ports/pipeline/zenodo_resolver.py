"""Port : résolution du concept DOI d'un DOI Zenodo.

Implémenté par `infrastructure.sources.zenodo.HttpZenodoResolver`.
"""

from typing import Protocol


class ZenodoResolver(Protocol):
    """Contrat de résolution d'un DOI Zenodo vers son concept DOI."""

    def resolve_concept_doi(self, doi: str) -> str | None:
        """Résout un DOI Zenodo (concept ou version) vers son concept DOI
        (l'identifiant stable, agnostique aux versions). Retourne `None` si
        le record n'expose pas de concept DOI (dépôt non versionné).

        Lève `domain.sources.zenodo.ZenodoResolutionError` en cas d'erreur
        temporaire (429, timeout) — l'appelant peut alors retenter plus tard.
        """
        ...
