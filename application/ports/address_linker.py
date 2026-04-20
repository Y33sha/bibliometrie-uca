"""Port : création des adresses et liens source_authorship_addresses.

Implémenté par `infrastructure.addresses.PgAddressLinker`.

Chaque adapter porte son propre cache d'adresses (raw_text → id) pour
éviter les lookups répétés dans un même run.
"""

from typing import Any, Protocol


class AddressLinker(Protocol):
    """Création d'adresses + liens authorship ↔ adresses."""

    def link(
        self,
        cur: Any,
        authorship_id: int,
        addr_texts: list[str],
        countries: list[str] | None = None,
    ) -> int:
        """Crée les adresses (si absentes) et les liens pour une authorship.

        `countries` : codes pays à propager sur les adresses créées, utilisés
        par ScanR qui fournit les pays détectés.

        Retourne le nombre de liens créés.
        """
        ...

    def clear_cache(self) -> None:
        """Vide le cache d'adresses (à appeler en fin de run)."""
        ...
