"""Query services autour des personnes.

Le package est organisé par thème :
- `list` : `persons_directory`, `search_persons`, `list_persons`, `DirectoryFilters`,
  `ListFilters`
- `facets` : `persons_facets`, `list_departments`, `list_roles`, `persons_stats`,
  `FacetFilters`
- `detail` : `get_person`, `person_profile`, `person_theses`, `person_addresses`
- `create` : `PgPersonsCreateQueries` (adapter du port
  `application.ports.persons_create`)
- `admin` : orphan authorships, name-form authorships, HAL duplicate accounts
"""

from infrastructure.db.queries.persons.create import PgPersonsCreateQueries
from infrastructure.db.queries.persons.detail import (
    get_person,
    person_addresses,
    person_dashboard,
    person_profile,
    person_subjects,
    person_theses,
)
from infrastructure.db.queries.persons.facets import (
    FacetFilters,
    list_departments,
    list_roles,
    persons_facets,
    persons_stats,
)
from infrastructure.db.queries.persons.list import (
    DirectoryFilters,
    ListFilters,
    list_persons,
    persons_directory,
    search_persons,
)

__all__ = [
    "DirectoryFilters",
    "FacetFilters",
    "ListFilters",
    "PgPersonsCreateQueries",
    "get_person",
    "list_departments",
    "list_persons",
    "list_roles",
    "person_addresses",
    "person_dashboard",
    "person_profile",
    "person_subjects",
    "person_theses",
    "persons_directory",
    "persons_facets",
    "persons_stats",
    "search_persons",
]
