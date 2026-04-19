"""Port : lectures/écritures pour les scripts de moissonnage HAL.

Implémenté par `infrastructure.db.queries.harvest.PgHarvestQueries`.
"""

from typing import Any, Protocol


class HarvestQueries(Protocol):
    """Opérations SQL sur `source_persons` pour les scripts de moissonnage HAL."""

    def fetch_hal_persons_missing_idref(self, cur: Any) -> list[dict[str, Any]]: ...

    def fetch_hal_persons_missing_identifiers(
        self, cur: Any
    ) -> list[tuple[int, int, int | None]]: ...

    def update_source_person_idref(self, cur: Any, source_person_id: int, idref: str) -> None: ...

    def fill_source_person_orcid_if_null(
        self, cur: Any, source_person_id: int, orcid: str
    ) -> bool: ...

    def fill_source_person_idref_if_null(
        self, cur: Any, source_person_id: int, idref: str
    ) -> bool: ...
