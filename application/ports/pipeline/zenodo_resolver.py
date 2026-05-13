"""Port : résolution d'un DOI Zenodo (concept → version).

Implémenté par `infrastructure.sources.zenodo.HttpZenodoResolver`.
"""

from typing import Protocol


class ZenodoResolver(Protocol):
    """Contrat de résolution d'un DOI Zenodo vers la version concrète."""

    def resolve(self, doi: str) -> str | None:
        """Résout un DOI Zenodo. Retourne le version-DOI réel, ou None si
        le DOI est déjà un version-DOI (rien à changer).

        Lève `domain.sources.zenodo.ZenodoResolutionError` en cas d'erreur temporaire
        (429, timeout) — l'appelant peut alors décider de retenter plus tard.
        """
        ...
