"""Port : lectures sur les adresses (consommé par le router addresses).

Implémenté par `infrastructure.db.queries.addresses.PgAsyncAddressesQueries`.
"""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class AddressListFilters:
    detected: str = "yes"  # all, yes, no
    validation: str = "pending"  # all, pending, confirmed, rejected
    search: str = ""
    search_mode: str = "contains"  # contains, not_contains


@dataclass(frozen=True, slots=True)
class AddressCountriesFilters:
    search: str = ""
    has_country: str = ""  # "yes", "no", ""
    country_code: str = ""
    suggested_country: str = ""
    suggest: bool = False


class AsyncAddressesQueries(Protocol):
    """Lectures async sur les adresses + pays."""

    async def resolve_default_structure_id(self) -> int: ...

    async def list_addresses(
        self,
        *,
        structure_id: int,
        filters: AddressListFilters,
        page: int,
        per_page: int,
    ) -> dict[str, Any]: ...

    async def get_address_basic(self, addr_id: int) -> dict[str, Any] | None: ...

    async def get_address_publications(self, addr_id: int, limit: int) -> list[dict[str, Any]]: ...

    async def get_address_structures(self, addr_id: int) -> list[dict[str, Any]]: ...

    async def get_structure_link(
        self, addr_id: int, structure_id: int
    ) -> dict[str, Any] | None: ...

    async def list_countries(self) -> list[dict[str, Any]]: ...

    async def country_exists(self, code: str) -> bool: ...

    async def address_exists(self, addr_id: int) -> bool: ...

    async def addresses_countries(
        self, *, filters: AddressCountriesFilters, page: int, per_page: int
    ) -> dict[str, Any]: ...

    async def suggest_countries(self, search: str) -> dict[str, Any]: ...

    async def admin_address_stats(self, structure_id: int) -> dict[str, Any]: ...
