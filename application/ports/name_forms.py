"""Port : SQL du peuplement de `person_name_forms`.

Implémenté par `infrastructure.db.queries.name_forms.PgNameFormsQueries`.
"""

from typing import Any, Protocol


class NameFormsQueries(Protocol):
    """Opérations SQL pour synchroniser `person_name_forms` depuis les sources."""

    def fetch_active_persons_names(self, cur: Any) -> list[dict[str, Any]]: ...

    def fetch_source_authorship_name_forms(self, cur: Any) -> list[dict[str, Any]]: ...

    def create_temp_raw_forms_table(self, cur: Any) -> None: ...

    def insert_raw_forms_batch(self, cur: Any, rows: list[tuple[str, int, str]]) -> None: ...

    def fetch_normalized_forms_from_temp(self, cur: Any) -> list[dict[str, Any]]: ...

    def drop_temp_raw_forms_table(self, cur: Any) -> None: ...

    def fetch_existing_name_forms(self, cur: Any) -> list[dict[str, Any]]: ...

    def update_name_form(
        self, cur: Any, form_id: int, person_ids: list[int], sources: list[str]
    ) -> None: ...

    def insert_name_form_with_merge(
        self, cur: Any, name_form: str, person_ids: list[int], sources: list[str]
    ) -> None: ...

    def delete_name_form(self, cur: Any, form_id: int) -> None: ...
