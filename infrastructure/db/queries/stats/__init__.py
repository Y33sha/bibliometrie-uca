"""Query services pour /api/stats/* (router pub_stats).

Le package est organisé par thème d'agrégat :
- `publishers` : `publisher_stats`
- `journals` : `journal_stats`
- `labs` : `stats_labs`
- `summary` : `stats_by_year`, `stats_summary`, `available_years`, `stats_facets`
- `_shared` : filtre APC + pagination partagés par tous les agrégats.

Chaque fonction prend un curseur DB + les paramètres de filtre/pagination ;
les agrégations APC utilisent le `root_structure_id` fourni par le caller
(résolu en amont via la config — pas de dépendance FastAPI ici).
"""

from infrastructure.db.queries.stats.journals import journal_stats
from infrastructure.db.queries.stats.labs import stats_labs
from infrastructure.db.queries.stats.publishers import publisher_stats
from infrastructure.db.queries.stats.summary import (
    available_years,
    stats_by_year,
    stats_facets,
    stats_summary,
)

__all__ = [
    "available_years",
    "journal_stats",
    "publisher_stats",
    "stats_by_year",
    "stats_facets",
    "stats_labs",
    "stats_summary",
]
