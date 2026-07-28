"""Port AddressRepository — contrat d'accès au cluster de tables des adresses.

L'adresse n'a pas d'objet de domaine : « agrégat » désigne ici le cluster que ce repository possède, sans racine d'entité côté `domain/`. Les invariants (autorité de `countries` sur `suggested_countries`, états d'un rattachement) sont portés par le SQL et les services.
"""

from typing import Protocol


class AddressRepository(Protocol):
    """Contrat d'accès aux tables addresses, address_structures, et propagations vers source_publications/publications.countries."""

    # ── Liens adresse ↔ structure ──────────────────────────────────

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

    def country_exists(self, code: str) -> bool:
        """Le code figure-t-il au référentiel `countries` ?

        `addresses.countries` est un tableau : aucune clé étrangère ne peut en garder les éléments, et les écritures de pays s'appuient sur cette lecture.
        """
        ...

    def set_countries(
        self,
        address_id: int,
        countries: list[str] | None,
    ) -> None:
        """Écrit les `countries` d'une adresse. Liste vide ou `None` : la colonne repasse à NULL. Lève `NotFoundError` si l'adresse est introuvable."""
        ...

    # Les opérations ensemblistes de pays (ajout par lot, propagation horizontale
    # et vers `source_publications` / `publications`) vivent dans le gateway
    # `application/ports/pipeline/countries.py`.
