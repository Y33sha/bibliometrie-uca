"""Query services autour des publications.

Le package est organisé par thème :
- `list` : `list_publications`, `export_publications_csv`, `export_theses_csv`, `ListFilters`
- `facets` : `publications_facets`, `FacetFilters`
- `detail` : `all_years`, `get_publication_detail`
- `create` : `PgPublicationsCreateQueries` (adapter du port
  `application.ports.publications_create`)

Les routers accèdent aux lectures via `from infrastructure.db.queries import
publications as pub_queries`. Le pipeline importe `PgPublicationsCreateQueries`
directement depuis `infrastructure.db.queries.publications.create`.
"""

from infrastructure.db.queries.publications.create import PgPublicationsCreateQueries
from infrastructure.db.queries.publications.detail import (
    all_years,
    get_publication_detail,
)
from infrastructure.db.queries.publications.facets import (
    FacetFilters,
    publications_facets,
)
from infrastructure.db.queries.publications.list import (
    ListFilters,
    export_publications_csv,
    export_theses_csv,
    list_publications,
)

__all__ = [
    "FacetFilters",
    "ListFilters",
    "PgPublicationsCreateQueries",
    "all_years",
    "export_publications_csv",
    "export_theses_csv",
    "get_publication_detail",
    "list_publications",
    "publications_facets",
]
