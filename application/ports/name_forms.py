"""Port : SQL du peuplement de `person_name_forms`.

Implémenté par `infrastructure.db.queries.name_forms.PgNameFormsQueries`.
"""

from typing import Any, Protocol


class NameFormsQueries(Protocol):
    """Opérations SQL pour synchroniser `person_name_forms` depuis les sources."""

    def fetch_persons_names(self, conn: Any) -> list[dict[str, Any]]: ...

    def fetch_source_authorship_name_forms(self, conn: Any) -> list[dict[str, Any]]: ...

    def create_temp_raw_forms_table(self, conn: Any) -> None: ...

    def insert_raw_forms_batch(self, conn: Any, rows: list[dict[str, Any]]) -> None: ...

    def fetch_normalized_forms_from_temp(self, conn: Any) -> list[dict[str, Any]]: ...

    def drop_temp_raw_forms_table(self, conn: Any) -> None: ...

    def fetch_existing_name_forms(self, conn: Any) -> list[dict[str, Any]]: ...

    def update_name_form(
        self, conn: Any, form_id: int, person_ids: list[int], sources: list[str]
    ) -> None: ...

    def insert_name_form_with_merge(
        self, conn: Any, name_form: str, person_ids: list[int], sources: list[str]
    ) -> None: ...

    def delete_name_form(self, conn: Any, form_id: int) -> None: ...
