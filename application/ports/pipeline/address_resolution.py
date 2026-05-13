"""Port : SQL du pipeline de résolution d'adresses.

Implémenté par `infrastructure.db.queries.address_resolution.PgAddressResolutionQueries`.
"""

from typing import Any, Protocol

from sqlalchemy import Connection


class AddressResolutionQueries(Protocol):
    """Opérations SQL pour résoudre les adresses → structures."""

    def load_name_forms(self, conn: Connection) -> list[dict[str, Any]]: ...

    def reset_auto_detected(self, conn: Connection) -> int: ...

    def reset_all_resolved_at(self, conn: Connection) -> None: ...

    def fetch_addresses_to_resolve(
        self, conn: Connection, *, incremental: bool
    ) -> list[tuple[int, str]]: ...

    def delete_obsolete_detections(
        self, conn: Connection, addr_id: int, kept_structure_ids: list[int]
    ) -> int: ...

    def unflag_obsolete_detections(
        self, conn: Connection, addr_id: int, kept_structure_ids: list[int]
    ) -> None: ...

    def upsert_detected_structure(
        self, conn: Connection, addr_id: int, structure_id: int, form_id: int
    ) -> None: ...

    def mark_address_resolved(self, conn: Connection, addr_id: int) -> None: ...
