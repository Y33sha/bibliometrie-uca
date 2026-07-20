"""Query service : référentiel des pays servi par `/api/countries`."""

from sqlalchemy import Connection, text

from application.ports.api.countries_queries import CountriesQueries, CountryOut
from domain.countries import NO_COUNTRY_CODE


class PgCountriesQueries(CountriesQueries):
    """Adapter SA pour `application.ports.api.countries_queries.CountriesQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_countries(self) -> list[CountryOut]:
        """Référentiel trié par libellé, l'absence de pays en tête.

        Les listes de choix la proposent d'abord : c'est l'arbitrage que la curation pose le plus souvent, et le seul qui ne se cherche pas par son nom.
        """
        rows = self._conn.execute(
            text("SELECT code, name FROM countries ORDER BY (code = :no_country) DESC, name"),
            {"no_country": NO_COUNTRY_CODE},
        ).all()
        return [CountryOut(code=r.code, name=r.name) for r in rows]


__all__ = ["PgCountriesQueries"]
