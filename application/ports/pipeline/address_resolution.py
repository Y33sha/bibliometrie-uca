"""Port : SQL du pipeline de résolution d'adresses.

Implémenté par `infrastructure.queries.pipeline.address_resolution.PgAddressResolutionQueries`.
"""

from typing import NamedTuple, Protocol

from sqlalchemy import Connection


class StructureNameForm(NamedTuple):
    """Forme normalisée d'une structure consommée par le matching adresses → structures.

    `requires_context_of` : liste des structure_ids dont au moins une forme doit aussi matcher pour valider cette forme (anti-faux-positifs cross-établissement, p.ex. `u999` exige UCA). `None` ou liste vide = pas de contexte requis.
    `is_excluding` : si TRUE et que la forme matche, retire la structure des résultats même si d'autres formes la matchent.
    """

    id: int
    structure_id: int
    form_text: str
    is_word_boundary: bool
    requires_context_of: list[int] | None
    is_excluding: bool
    struct_code: str | None
    struct_type: str


class AddressResolutionQueries(Protocol):
    """Opérations SQL pour résoudre les adresses → structures."""

    def load_name_forms(self, conn: Connection) -> list[StructureNameForm]: ...

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
