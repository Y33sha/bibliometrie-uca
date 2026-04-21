"""Port AsyncAddressRepository — contrat d'accès à l'agrégat Address.

Implémenté par infrastructure/repositories/async_address_repository.py.
"""

from typing import Protocol


class AsyncAddressRepository(Protocol):
    """Contrat async d'accès aux tables addresses, address_structures, et
    propagations vers source_publications/publications.countries."""

    # ── Liens address ↔ structure ──────────────────────────────────

    async def reset_manual_link(self, address_id: int, structure_id: int) -> None: ...

    async def upsert_structure_link(
        self,
        address_id: int,
        structure_id: int,
        is_confirmed: bool,
    ) -> None: ...

    async def batch_reset_manual_links(
        self,
        address_ids: list[int],
        structure_id: int,
    ) -> int: ...

    async def batch_upsert_structure_links(
        self,
        address_ids: list[int],
        structure_id: int,
        is_confirmed: bool,
    ) -> None: ...

    async def delete_manual_structure_link(
        self,
        address_id: int,
        structure_id: int,
    ) -> bool: ...

    # ── Pays ───────────────────────────────────────────────────────

    async def set_countries(
        self,
        address_id: int,
        countries: list[str] | None,
    ) -> None: ...

    async def propagate_countries_to_similar_address(
        self,
        address_id: int,
    ) -> list[int]: ...

    async def batch_add_country_by_ids(
        self,
        country_code: str,
        address_ids: list[int],
    ) -> list[int]: ...

    async def batch_add_country_by_where(
        self,
        country_code: str,
        where_clause: str,
        where_params: list,
    ) -> list[int]: ...

    async def propagate_countries_across_similar_addresses(self) -> list[int]: ...

    # ── Propagation vers source_publications et publications ───────

    async def refresh_source_publications_countries(
        self,
        address_ids: list[int],
    ) -> int: ...

    async def refresh_publications_countries_for_addresses(
        self,
        address_ids: list[int],
    ) -> int: ...
