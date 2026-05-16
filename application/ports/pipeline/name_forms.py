"""Port : SQL du peuplement de `person_name_forms`.

Implémenté par `infrastructure.queries.name_forms.PgNameFormsQueries`.

Workflow attendu : l'orchestrateur peuple une table temp `_raw_forms`
avec les formes calculées depuis `persons` (compute_person_name_forms),
puis appelle `sync_from_raw_forms` qui agrège (UNION SQL avec
`source_authorships`) et synchronise `person_name_forms`.
"""

from typing import Any, Protocol

from sqlalchemy import Connection


class NameFormsQueries(Protocol):
    """Opérations SQL pour synchroniser `person_name_forms` depuis les sources."""

    def fetch_persons_names(self, conn: Connection) -> list[dict[str, Any]]: ...

    def create_temp_raw_forms_table(self, conn: Connection) -> None: ...

    def insert_raw_forms_batch(self, conn: Connection, rows: list[dict[str, Any]]) -> None: ...

    def drop_temp_raw_forms_table(self, conn: Connection) -> None: ...

    def sync_from_raw_forms(self, conn: Connection) -> tuple[int, int, int]:
        """Agrège `_raw_forms` ∪ `source_authorships` et synchronise
        `person_name_forms`. Retourne `(inserted, updated, deleted)`."""
        ...
