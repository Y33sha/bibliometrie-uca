"""Port : création des adresses et liens source_authorship_addresses.

Implémenté par `infrastructure.repositories.address_linker.PgAddressLinker`.

Chaque adapter porte son propre cache d'adresses (raw_text → id) pour
éviter les lookups répétés dans un même run.
"""

from typing import Protocol

from sqlalchemy import Connection


class AddressLinker(Protocol):
    """Création d'adresses + liens authorship ↔ adresses."""

    def link(
        self,
        conn: Connection,
        authorship_id: int,
        addr_texts: list[str],
        countries: list[str] | None = None,
        suggested_countries: list[str] | None = None,
    ) -> int:
        """Crée les adresses (si absentes) et les liens pour une authorship.

        `countries` : codes pays à propager sur `addresses.countries` (autorité),
        utilisés par ScanR qui fournit les pays détectés dans le texte.

        `suggested_countries` : codes pays à propager sur
        `addresses.suggested_countries` (suggestion à valider, jamais autorité),
        utilisés par OpenAlex dont le `country_code` provient de la structure
        désambiguïsée algorithmiquement (faillible). Propagés uniquement sur les
        adresses encore sans pays ni suggestion.

        Retourne le nombre de liens créés.
        """
        ...

    def clear_cache(self) -> None:
        """Vide le cache d'adresses (à appeler en fin de run)."""
        ...
