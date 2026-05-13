"""Port : SQL du peuplement de `person_name_forms`.

Implémenté par `infrastructure.db.queries.name_forms.PgNameFormsQueries`.
"""

from typing import Any, Protocol

from sqlalchemy import Connection

from domain.persons.name_forms import PersonsDict


class NameFormsQueries(Protocol):
    """Opérations SQL pour synchroniser `person_name_forms` depuis les sources."""

    def fetch_persons_names(self, conn: Connection) -> list[dict[str, Any]]: ...

    def fetch_source_authorship_name_forms(self, conn: Connection) -> list[dict[str, Any]]: ...

    def create_temp_raw_forms_table(self, conn: Connection) -> None: ...

    def insert_raw_forms_batch(self, conn: Connection, rows: list[dict[str, Any]]) -> None: ...

    def fetch_normalized_forms_from_temp(self, conn: Connection) -> list[dict[str, Any]]: ...

    def drop_temp_raw_forms_table(self, conn: Connection) -> None: ...

    def fetch_existing_name_forms(self, conn: Connection) -> list[dict[str, Any]]: ...

    def update_name_form(self, conn: Connection, form_id: int, persons: PersonsDict) -> None: ...

    def insert_name_form(self, conn: Connection, name_form: str, persons: PersonsDict) -> None: ...

    def delete_name_form(self, conn: Connection, form_id: int) -> None: ...
