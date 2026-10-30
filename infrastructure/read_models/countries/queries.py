"""Référentiel des pays servi par `/api/countries`."""

from sqlalchemy import Connection, text

from domain.countries import NO_COUNTRY_CODE
from infrastructure.read_models.countries.models import (
    CountryOut,
)


class CountriesQueries:
    """Lecture du référentiel des pays."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_countries(self) -> list[CountryOut]:
        """Renvoie le référentiel trié par libellé, l'absence de pays en tête.

        L'absence de pays est l'arbitrage manuel le plus fréquent, et le seul introuvable par son nom.
        """
        rows = self._conn.execute(
            text("SELECT code, name FROM countries ORDER BY (code = :no_country) DESC, name"),
            {"no_country": NO_COUNTRY_CODE},
        ).all()
        return [CountryOut(code=r.code, name=r.name) for r in rows]


__all__ = ["CountriesQueries"]
