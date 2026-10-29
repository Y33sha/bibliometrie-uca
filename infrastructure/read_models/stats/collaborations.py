"""Agrégat des collaborations internationales par pays.

Compte, pour chaque pays étranger, le nombre de publications du périmètre qui lui sont co-affiliées, en dépliant la colonne `publications.countries` (ensemble des pays présents dans les affiliations d'une publication). Le pays de l'établissement et l'absence de pays sont écartés (`NON_INTERNATIONAL_COUNTRY_CODES`).
"""

from sqlalchemy import Connection, text

from domain.countries import NON_INTERNATIONAL_COUNTRY_CODES
from infrastructure.read_models.publications.filtering import (
    filter_context,
    publication_filter_where,
)
from infrastructure.read_models.publications.models import PublicationFilters
from infrastructure.read_models.stats.models import (
    CollaborationsResponse,
    CountryCollaboration,
)

_NON_INTERNATIONAL = sorted(NON_INTERNATIONAL_COUNTRY_CODES)


class StatsCollaborationQueries:
    _conn: Connection

    def collaborations(self, *, filters: PublicationFilters) -> CollaborationsResponse:
        """Collaborations internationales sous les filtres : nombre de publications co-affiliées à chaque pays étranger, du plus fréquent au moins fréquent, nombre de publications en collaboration internationale (au moins un pays étranger) et total du corpus filtré, pour exprimer une part."""
        where, binds = publication_filter_where(filters, filter_context(self._conn, filters))
        binds["non_international"] = _NON_INTERNATIONAL
        self._conn.execute(text("SET LOCAL jit = off"))

        per_country = (
            "SELECT country AS code, COUNT(DISTINCT p.id) AS value "
            "FROM publications p "
            "CROSS JOIN LATERAL unnest(p.countries) AS country "
            f"WHERE {where} AND country <> ALL(:non_international) "
            "GROUP BY country ORDER BY value DESC"
        )
        rows = self._conn.execute(text(per_country), binds).all()

        # Numérateur (publications avec au moins un pays étranger) et dénominateur (corpus filtré), au grain publication.
        totals = (
            "SELECT COUNT(DISTINCT p.id) AS total, "
            "COUNT(DISTINCT p.id) FILTER (WHERE EXISTS ("
            "SELECT 1 FROM unnest(p.countries) c WHERE c <> ALL(:non_international)"
            ")) AS international "
            "FROM publications p "
            f"WHERE {where}"
        )
        agg = self._conn.execute(text(totals), binds).one()

        return CollaborationsResponse(
            rows=[CountryCollaboration(code=r.code, value=r.value) for r in rows],
            international_count=agg.international or 0,
            total_count=agg.total or 0,
        )
