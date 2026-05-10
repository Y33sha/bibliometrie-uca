"""Port : lectures pour `create_persons_from_source_authorships`.

Implémenté par `infrastructure.db.queries.persons.create.PgPersonsCreateQueries`.
"""

from typing import Any, Protocol

from sqlalchemy import Connection


class PersonsCreateQueries(Protocol):
    """Opérations SQL pour le rattachement des authorships aux personnes."""

    def fetch_unlinked_authorships(self, conn: Connection) -> list[dict[str, Any]]: ...

    def fetch_linked_authorships(self, conn: Connection) -> list[dict[str, Any]]: ...

    def fetch_hal_account_to_person_map(self, conn: Connection) -> dict[int, int]: ...

    def fetch_idref_to_person_map(self, conn: Connection) -> dict[str, int]: ...

    def fetch_orcid_to_person_map(self, conn: Connection) -> dict[str, int]: ...

    def fetch_name_form_map(self, conn: Connection) -> dict[str, list[int]]: ...
