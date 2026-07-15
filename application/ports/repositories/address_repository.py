"""Port AddressRepository — contrat d'accès au cluster de tables des adresses.

L'adresse n'a pas d'objet de domaine : « agrégat » désigne ici le cluster que ce repository possède, sans racine d'entité côté `domain/`. Les invariants (autorité de `countries` sur `suggested_countries`, états d'un rattachement) sont portés par le SQL et les services.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AddressCountryFilter:
    """Critères de sélection d'adresses pour une attribution de pays en masse.

    Combinés en AND. `has_country` : True → `countries` renseigné, False → NULL, None → critère inactif. `country_code` / `suggested_country` : code présent dans la colonne correspondante."""

    search: str | None = None
    has_country: bool | None = None
    country_code: str | None = None
    suggested_country: str | None = None

    @property
    def is_empty(self) -> bool:
        """Vrai si aucun critère n'est renseigné."""
        return not (
            self.search
            or self.has_country is not None
            or self.country_code
            or self.suggested_country
        )


class AddressRepository(Protocol):
    """Contrat d'accès aux tables addresses, address_structures, et
    propagations vers source_publications/publications.countries."""

    # ── Liens address ↔ structure ──────────────────────────────────

    def reset_manual_link(self, address_id: int, structure_id: int) -> None:
        """Annule la décision manuelle sur un rattachement : supprime le lien s'il est purement manuel (`matched_form_id IS NULL` — aucune détection ne l'atteste), et repasse `is_confirmed` à NULL (pending) sur la détection qui subsiste."""
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
        """Sous-ensemble de `address_ids` qui contribue au calcul `in_perimeter` pour `structure_id` : lien existant avec `is_confirmed IS DISTINCT FROM FALSE` (NULL ou TRUE).

        Sert aux services de validation à détecter les opérations no-op (confirmer une adresse déjà auto-détectée) et à éviter une propagation d'`in_perimeter` inutile.
        """
        ...

    # ── Pays ───────────────────────────────────────────────────────

    def set_countries(
        self,
        address_id: int,
        countries: list[str] | None,
    ) -> None:
        """Écrit les `countries` d'une adresse. Liste vide ou `None` : la colonne repasse à NULL."""
        ...

    def batch_add_country_by_ids(
        self,
        country_code: str,
        address_ids: list[int],
    ) -> list[int]:
        """Ajoute `country_code` aux `countries` des adresses données, sans doublon ni écrasement des codes déjà posés. Retourne les ids atteints."""
        ...

    def batch_add_country_by_filter(
        self,
        country_code: str,
        criteria: AddressCountryFilter,
    ) -> list[int]:
        """Comme `batch_add_country_by_ids`, sur les adresses retenues par `criteria`. Retourne les ids modifiés ; critères tous vides : aucune écriture, `[]`."""
        ...

    def propagate_countries_across_similar_addresses(
        self,
        source_ids: list[int],
    ) -> list[int]:
        """Propage `countries` depuis les adresses `source_ids` vers celles qui partagent leur `normalized_text` et portent un `countries` différent (ou NULL). Retourne les ids propagés ; `source_ids` vide : `[]`.

        Deux restrictions : la source doit avoir un `countries` non NULL, et la jumelle un `normalized_text` d'au moins 5 caractères — un texte plus court rapprocherait des adresses sans rapport.
        """
        ...

    # ── Propagation vers source_publications et publications ──

    def refresh_source_publications_countries(
        self,
        address_ids: list[int],
    ) -> int:
        """Recalcule `source_publications.countries` (union des pays des adresses de leurs signatures) pour les documents rattachés à l'une des `address_ids`. Idempotent. Retourne le nombre de documents mis à jour."""
        ...

    def refresh_publications_countries_for_addresses(
        self,
        address_ids: list[int],
    ) -> int:
        """Recalcule `publications.countries` (union des `source_publications.countries`) pour les publications rattachées à l'une des `address_ids`. Idempotent. Retourne le nombre de publications mises à jour."""
        ...
