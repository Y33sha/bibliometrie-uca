"""Query services autour des personnes.

Le package est organisé par thème :
- `list` : `persons_directory`, `search_persons`, `list_persons`
- `facets` : `persons_facets`, `list_departments`, `list_roles`, `persons_stats`
- `detail` : `get_person`, `person_profile`, `person_theses`, `person_addresses`,
  `person_dashboard`, `person_subjects`
- `admin` : `person_exists`, orphan authorships, name-form authorships
- `create` : `PgPersonsCreateQueries` (adapter sync du port
  `application.ports.persons_create`, consommé par le pipeline)

`PgPersonsQueries` agrège l'ensemble des fonctions de lecture + admin
sous le port `application.ports.persons_queries.PersonsQueries`.
Les dataclasses `DirectoryFilters` / `ListFilters` / `FacetFilters`
vivent côté port (source de vérité), ici on type `filters: Any`.
"""

# Annotations différées : sinon `list[int]` est résolu comme le sous-module
# `.list` (le `from .list import …` ci-dessous l'attache au package, et le
# namespace global du __init__ shadow le builtin `list`).
from __future__ import annotations

from typing import Any

from sqlalchemy import Connection

from infrastructure.db.queries.persons.admin import (
    list_orphan_authorships as _list_orphan_authorships,
)
from infrastructure.db.queries.persons.admin import (
    name_form_authorships as _name_form_authorships,
)
from infrastructure.db.queries.persons.admin import (
    name_form_remaining_authorships as _name_form_remaining_authorships,
)
from infrastructure.db.queries.persons.admin import (
    orphan_authorships_count as _orphan_authorships_count,
)
from infrastructure.db.queries.persons.admin import (
    person_exists as _person_exists,
)
from infrastructure.db.queries.persons.create import PgPersonsCreateQueries
from infrastructure.db.queries.persons.detail import (
    get_person as _get_person,
)
from infrastructure.db.queries.persons.detail import (
    person_addresses as _person_addresses,
)
from infrastructure.db.queries.persons.detail import (
    person_dashboard as _person_dashboard,
)
from infrastructure.db.queries.persons.detail import (
    person_profile as _person_profile,
)
from infrastructure.db.queries.persons.detail import (
    person_subjects as _person_subjects,
)
from infrastructure.db.queries.persons.detail import (
    person_theses as _person_theses,
)
from infrastructure.db.queries.persons.facets import (
    list_departments as _list_departments,
)
from infrastructure.db.queries.persons.facets import (
    list_roles as _list_roles,
)
from infrastructure.db.queries.persons.facets import (
    persons_facets as _persons_facets,
)
from infrastructure.db.queries.persons.facets import (
    persons_stats as _persons_stats,
)
from infrastructure.db.queries.persons.list import (
    list_persons as _list_persons,
)
from infrastructure.db.queries.persons.list import (
    persons_directory as _persons_directory,
)
from infrastructure.db.queries.persons.list import (
    search_persons as _search_persons,
)


class PgPersonsQueries:
    """Adapter SA pour `application.ports.persons_queries.PersonsQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── Annuaire / recherche / liste admin ─────────────────────────

    def persons_directory(self, **kwargs: Any) -> dict[str, Any]:
        return _persons_directory(self._conn, **kwargs)

    def search_persons(self, **kwargs: Any) -> list[dict[str, Any]]:
        return _search_persons(self._conn, **kwargs)

    def list_persons(self, **kwargs: Any) -> dict[str, Any]:
        return _list_persons(self._conn, **kwargs)

    # ── Facettes / listes de référence / stats ─────────────────────

    def persons_facets(self, **kwargs: Any) -> dict[str, Any]:
        return _persons_facets(self._conn, **kwargs)

    def list_departments(self) -> list[dict[str, Any]]:
        return _list_departments(self._conn)

    def list_roles(self) -> list[dict[str, Any]]:
        return _list_roles(self._conn)

    def persons_stats(self) -> dict[str, Any]:
        return _persons_stats(self._conn)

    # ── Détail d'une personne ──────────────────────────────────────

    def get_person(self, person_id: int) -> dict[str, Any] | None:
        return _get_person(self._conn, person_id)

    def person_profile(self, person_id: int) -> dict[str, Any] | None:
        return _person_profile(self._conn, person_id)

    def person_theses(self, person_id: int) -> dict[str, Any]:
        return _person_theses(self._conn, person_id)

    def person_addresses(self, person_id: int, *, page: int, per_page: int) -> dict[str, Any]:
        return _person_addresses(self._conn, person_id, page=page, per_page=per_page)

    def person_dashboard(self, person_id: int) -> dict[str, Any]:
        return _person_dashboard(self._conn, person_id)

    def person_subjects(self, person_id: int, *, limit: int) -> list[dict[str, Any]]:
        return _person_subjects(self._conn, person_id, limit=limit)

    # ── Admin : existence, orphan authorships, name forms ──────────

    def person_exists(self, person_id: int) -> bool:
        return _person_exists(self._conn, person_id)

    def orphan_authorships_count(self) -> dict[str, Any]:
        return _orphan_authorships_count(self._conn)

    def list_orphan_authorships(self, **kwargs: Any) -> dict[str, Any]:
        return _list_orphan_authorships(self._conn, **kwargs)

    def name_form_authorships(self, person_id: int, name_form: str) -> dict[str, Any]:
        return _name_form_authorships(self._conn, person_id, name_form)

    def name_form_remaining_authorships(self, person_id: int, name_form: str) -> int:
        return _name_form_remaining_authorships(self._conn, person_id, name_form)


__all__ = ["PgPersonsCreateQueries", "PgPersonsQueries"]
