"""Port AddressRepository — contrat d'accès au cluster de tables des adresses.

L'adresse n'a pas d'objet de domaine : « agrégat » désigne ici le cluster que ce repository possède, sans racine d'entité côté `domain/`. Le domaine, le SQL et les services garantissent les invariants : préséance des pays candidats, états d'un rattachement.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AddressCountryFilter:
    """Critères de sélection d'adresses par leur pays, pour la liste d'attribution et l'attribution en masse.

    Combinés en AND. `search` : sous-chaîne cherchée dans le texte de l'adresse, insensible à la casse et aux accents. `has_country` : True → pays renseigné, False → aucun pays, None → critère inactif. `country_code` : pays retenu."""

    search: str | None = None
    has_country: bool | None = None
    country_code: str | None = None

    @property
    def is_empty(self) -> bool:
        """Vrai si aucun critère n'est renseigné."""
        return not (self.search or self.has_country is not None or self.country_code)


class AddressRepository(Protocol):
    """Contrat des écritures sur les adresses : liens aux structures, pays saisis à la main."""

    # ── Liens adresse ↔ structure ──────────────────────────────────

    def reset_manual_link(self, address_id: int, structure_id: int) -> None:
        """Annule la décision manuelle sur un rattachement : supprime le lien qu'aucune détection n'atteste, et rend une détection à l'état non décidé."""
        ...

    def upsert_structure_link(
        self,
        address_id: int,
        structure_id: int,
        is_confirmed: bool,
    ) -> None:
        """Pose la décision manuelle sur un rattachement (`is_confirmed` : TRUE confirmé, FALSE rejeté), en créant le lien s'il n'existe pas."""
        ...

    def batch_reset_manual_links(
        self,
        address_ids: list[int],
        structure_id: int,
    ) -> int:
        """`reset_manual_link` sur un lot. Retourne le nombre de rattachements touchés : liens purement manuels supprimés + détections repassées à pending."""
        ...

    def batch_upsert_structure_links(
        self,
        address_ids: list[int],
        structure_id: int,
        is_confirmed: bool,
    ) -> None:
        """`upsert_structure_link` sur un lot."""
        ...

    def which_contribute_to_perimeter(
        self,
        address_ids: list[int],
        structure_id: int,
    ) -> set[int]:
        """Sous-ensemble de `address_ids` dont le lien à `structure_id` compte pour le périmètre : lien confirmé ou non décidé."""
        ...

    # ── Pays ───────────────────────────────────────────────────────

    def country_exists(self, code: str) -> bool:
        """Le code figure-t-il au référentiel `countries` ? Les saisies de pays s'appuient sur cette lecture pour refuser un code inconnu."""
        ...

    def set_manual_countries(self, address_id: int, countries: list[str] | None) -> None:
        """Fait de `countries` les pays saisis à la main (candidats `manual`) de l'adresse, et la met dans la file `address_candidates_queue`. Liste vide ou `None` : l'adresse est rendue aux moyens automatiques. Lève `NotFoundError` si l'adresse est introuvable."""
        ...

    def add_manual_country_by_ids(self, country_code: str, address_ids: list[int]) -> list[int]:
        """Saisit à la main, pour chaque adresse, ses pays retenus et `country_code` (candidats `manual`), et la met dans la file `address_candidates_queue`. Retourne les ids atteints."""
        ...

    def add_manual_country_by_filter(
        self, country_code: str, criteria: AddressCountryFilter
    ) -> list[int]:
        """Comme `add_manual_country_by_ids`, sur les adresses retenues par `criteria`. Retourne les ids atteints ; critères tous vides : aucune écriture, `[]`."""
        ...
