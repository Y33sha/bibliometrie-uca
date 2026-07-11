"""Port AddressRepository — contrat d'accès à l'agrégat Address."""

from typing import Any, Protocol


class AddressRepository(Protocol):
    """Contrat d'accès aux tables addresses, address_structures, et
    propagations vers source_publications/publications.countries."""

    # ── Liens address ↔ structure ──────────────────────────────────

    def reset_manual_link(self, address_id: int, structure_id: int) -> None: ...

    def upsert_structure_link(
        self,
        address_id: int,
        structure_id: int,
        is_confirmed: bool,
    ) -> None: ...

    def batch_reset_manual_links(
        self,
        address_ids: list[int],
        structure_id: int,
    ) -> int: ...

    def batch_upsert_structure_links(
        self,
        address_ids: list[int],
        structure_id: int,
        is_confirmed: bool,
    ) -> None: ...

    def which_contribute_to_perimeter(
        self,
        address_ids: list[int],
        structure_id: int,
    ) -> set[int]: ...

    """Sous-ensemble de `address_ids` qui contribue actuellement au calcul
    `in_perimeter` pour `structure_id` — i.e. lien existant avec
    `is_confirmed IS DISTINCT FROM FALSE` (NULL ou TRUE).

    Utilisé par les services de validation pour détecter les opérations
    no-op (ex: cliquer "Relier" sur une adresse déjà auto-détectée) et
    skipper la propagation UCA inutile.
    """

    # ── Pays ───────────────────────────────────────────────────────

    def set_countries(
        self,
        address_id: int,
        countries: list[str] | None,
    ) -> None: ...

    def batch_add_country_by_ids(
        self,
        country_code: str,
        address_ids: list[int],
    ) -> list[int]: ...

    def batch_add_country_by_where(
        self,
        country_code: str,
        where_clause: str,
        # Liste de bind-params SQL hétérogènes (str/int/bool/list[int]/...).
        # `Any` justifié : frontière SQL, types dépendent du `where_clause`.
        where_params: list[Any],
    ) -> list[int]: ...

    def propagate_countries_across_similar_addresses(
        self,
        source_ids: list[int],
    ) -> list[int]:
        """Propage `countries` depuis les adresses `source_ids` vers les autres adresses qui partagent leur `normalized_text` et qui ont un `countries` différent (ou NULL). Retourne les IDs propagés. `source_ids` doit être non vide ; sinon retourne `[]` immédiatement."""
        ...

    # ── Propagation vers source_publications et publications ──

    def refresh_source_publications_countries(
        self,
        address_ids: list[int],
    ) -> int: ...

    def refresh_publications_countries_for_addresses(
        self,
        address_ids: list[int],
    ) -> int: ...
