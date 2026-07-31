"""Port : SQL du peuplement de `person_name_forms`.

Quatre autres tables portent des formes de nom — structures, revues, éditeurs, lieux — chacune avec ses propres chemins d'écriture.

Implémenté par `infrastructure.pipeline.persons.name_forms.PgPersonNameFormsQueries`.

Workflow attendu : l'orchestrateur peuple une table temp `_raw_forms` avec les formes calculées depuis `persons` (compute_person_name_forms), puis appelle `sync_from_raw_forms` qui agrège (UNION SQL avec `source_authorships`) et synchronise `person_name_forms`.
"""

from typing import NamedTuple, Protocol, TypedDict

from sqlalchemy import Connection


class PersonNameRow(NamedTuple):
    """Projection `persons` consommée par `populate_person_name_forms` : id + parts du nom (trimmées en SQL)."""

    id: int
    first_name: str | None
    last_name: str


class RawFormBatchItem(TypedDict):
    """Ligne du batch executemany vers la table temp `_raw_forms`."""

    raw_text: str
    person_id: int
    source: str


class SyncCounts(NamedTuple):
    """Bilan d'une synchronisation de `person_name_forms`."""

    inserted: int
    updated: int
    deleted: int


class PersonNameFormsQueries(Protocol):
    """Opérations SQL pour synchroniser `person_name_forms` depuis les sources."""

    def fetch_persons_names(self, conn: Connection) -> list[PersonNameRow]:
        """`(id, first_name, last_name)` de toutes les personnes portant un nom."""
        ...

    def create_temp_raw_forms_table(self, conn: Connection) -> None:
        """Crée la table temporaire `_raw_forms(raw_text, person_id, source)` que l'orchestrateur remplit avec les formes calculées depuis `persons`."""
        ...

    def insert_raw_forms_batch(self, conn: Connection, rows: list[RawFormBatchItem]) -> None:
        """Insert massif de formes brutes dans la table temporaire `_raw_forms`."""
        ...

    def drop_temp_raw_forms_table(self, conn: Connection) -> None:
        """Supprime la table temporaire `_raw_forms`."""
        ...

    def sync_from_raw_forms(self, conn: Connection) -> SyncCounts:
        """Agrège `_raw_forms` ∪ `source_authorships` et synchronise `person_name_forms`."""
        ...
