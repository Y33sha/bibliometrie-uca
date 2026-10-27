"""Agrégat des collaborations internationales par pays.

Compte, pour chaque pays étranger, le nombre de publications du périmètre qui lui sont co-affiliées, en dépliant la colonne `publications.countries` (ensemble des pays présents dans les affiliations d'une publication). Le pays de rattachement du périmètre est exclu : l'indicateur mesure l'ouverture *internationale*, pas la présence domestique (quasi universelle).
"""

from sqlalchemy import Connection, text

from infrastructure.read_models.publications.filtering import (
    filter_context,
    publication_filter_where,
)
from infrastructure.read_models.publications.models import PublicationFilters
from infrastructure.read_models.stats.models import (
    CollaborationsResponse,
    CountryCollaboration,
)

# Pays de rattachement du périmètre (France), exclu du décompte des collaborations internationales. Codes pays en ISO 3166-1 alpha-2 minuscule, comme stockés dans `publications.countries`.
_DOMESTIC_COUNTRY = "fr"


class StatsCollaborationQueries:
    _conn: Connection

    def collaborations(self, *, filters: PublicationFilters) -> CollaborationsResponse:
        """Collaborations internationales sous les filtres. Retourne les lignes `{code, value}` (un pays étranger, nombre de publications co-affiliées) triées par décompte décroissant, ainsi que le nombre de publications en collaboration internationale (au moins un pays étranger) et le total du corpus filtré — de quoi exprimer une part."""
        where, binds = publication_filter_where(filters, filter_context(self._conn, filters))
        binds["domestic_country"] = _DOMESTIC_COUNTRY
        self._conn.execute(text("SET LOCAL jit = off"))

        per_country = (
            "SELECT country AS code, COUNT(DISTINCT p.id) AS value "
            "FROM publications p "
            "LEFT JOIN serials j ON j.id = p.serial_id "
            "CROSS JOIN LATERAL unnest(p.countries) AS country "
            f"WHERE {where} AND country <> :domestic_country "
            "GROUP BY country ORDER BY value DESC"
        )
        rows = self._conn.execute(text(per_country), binds).all()

        # Numérateur (publications avec au moins un pays étranger) et dénominateur (corpus filtré), au grain publication : `array_remove` retire le pays domestique ; un reste non vide signale l'international.
        totals = (
            "SELECT COUNT(DISTINCT p.id) AS total, "
            "COUNT(DISTINCT p.id) FILTER "
            "(WHERE cardinality(array_remove(p.countries, :domestic_country)) > 0) AS international "
            "FROM publications p "
            "LEFT JOIN serials j ON j.id = p.serial_id "
            f"WHERE {where}"
        )
        agg = self._conn.execute(text(totals), binds).one()

        return CollaborationsResponse(
            rows=[CountryCollaboration(code=r.code, value=r.value) for r in rows],
            international_count=agg.international or 0,
            total_count=agg.total or 0,
        )
