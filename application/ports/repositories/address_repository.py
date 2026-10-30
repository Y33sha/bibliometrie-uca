"""Port AddressRepository : écritures sur les adresses et leurs liens.

L'adresse est sans objet de domaine. Le domaine, le SQL et les services garantissent les invariants : préséance des pays candidats, états d'un rattachement.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AddressCountryFilter:
    """Critères de sélection d'adresses par leur pays, combinés en AND, pour la liste d'attribution et l'attribution en masse."""

    search: str | None = None
    """Sous-chaîne du texte de l'adresse, insensible à la casse et aux accents."""
    has_country: bool | None = None
    """Vrai pour un pays renseigné, faux pour aucun pays, `None` sans critère."""
    country_code: str | None = None
    """Pays retenu."""

    @property
    def is_empty(self) -> bool:
        """Vrai si aucun critère n'est renseigné."""
        return not (self.search or self.has_country is not None or self.country_code)


class AddressRepository(Protocol):
    """Contrat des écritures sur les adresses : liens aux structures, pays saisis à la main."""

    # ── Liens adresse ↔ structure ──────────────────────────────────

    def reset_manual_link(self, address_id: int, structure_id: int) -> None:
        """Annule la décision manuelle sur un rattachement. Supprime un lien sans détection, et remet une détection à l'état non décidé."""
        ...

    def upsert_structure_link(
        self,
        address_id: int,
        structure_id: int,
        is_confirmed: bool,
    ) -> None:
        """Confirme (`is_confirmed` vrai) ou rejette à la main un rattachement, en créant le lien au besoin."""
        ...

    def batch_reset_manual_links(
        self,
        address_ids: list[int],
        structure_id: int,
    ) -> int:
        """Applique `reset_manual_link` à un lot. Renvoie le nombre de liens manuels supprimés et de détections remises en attente."""
        ...

    def batch_upsert_structure_links(
        self,
        address_ids: list[int],
        structure_id: int,
        is_confirmed: bool,
    ) -> None:
        """Applique `upsert_structure_link` à un lot."""
        ...

    def which_contribute_to_perimeter(
        self,
        address_ids: list[int],
        structure_id: int,
    ) -> set[int]:
        """Renvoie, parmi les adresses données, celles à lien confirmé ou non décidé avec la structure. Ces liens comptent pour le périmètre."""
        ...

    # ── Pays ───────────────────────────────────────────────────────

    def country_exists(self, code: str) -> bool:
        """Indique si le code figure au référentiel `countries`."""
        ...

    def set_manual_countries(self, address_id: int, countries: list[str] | None) -> None:
        """Enregistre `countries` comme pays saisis à la main de l'adresse (candidats `manual`), et met l'adresse dans la file `address_candidates_queue`.

        Une liste vide ou `None` supprime la saisie manuelle.

        Raises:
            NotFoundError: adresse introuvable.
        """
        ...

    def add_manual_country_by_ids(self, country_code: str, address_ids: list[int]) -> list[int]:
        """Enregistre comme pays saisis à la main de chaque adresse (candidats `manual`) ses pays retenus et `country_code`, et met l'adresse dans la file `address_candidates_queue`. Renvoie les ids des adresses trouvées."""
        ...

    def add_manual_country_by_filter(
        self, country_code: str, criteria: AddressCountryFilter
    ) -> list[int]:
        """Applique `add_manual_country_by_ids` aux adresses sélectionnées par les critères. Renvoie leurs ids, ou `[]` sans critère."""
        ...
