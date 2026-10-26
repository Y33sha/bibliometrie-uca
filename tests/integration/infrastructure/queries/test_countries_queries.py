"""Tests d'intégration pour `infrastructure.read_models.countries.queries`."""

from domain.countries import NO_COUNTRY_CODE
from infrastructure.read_models.countries.queries import CountriesQueries
from tests.integration.helpers.addresses import ensure_country


class TestListCountries:
    def test_puts_the_absence_of_country_first(self, sa_sync_conn):
        """L'absence de pays ouvre la liste : c'est l'arbitrage le plus fréquent, et le seul qui ne se cherche pas par son nom."""
        ensure_country(sa_sync_conn, "FR", name="France")
        ensure_country(sa_sync_conn, NO_COUNTRY_CODE, name="Non applicable")

        codes = [r.code.strip() for r in CountriesQueries(sa_sync_conn).list_countries()]
        assert codes[0] == NO_COUNTRY_CODE
        assert "FR" in codes

    def test_sorts_the_rest_by_name(self, sa_sync_conn):
        ensure_country(sa_sync_conn, "ZA", name="Afrique du Sud")
        ensure_country(sa_sync_conn, "FR", name="France")

        names = [
            r.name
            for r in CountriesQueries(sa_sync_conn).list_countries()
            if r.code.strip() != NO_COUNTRY_CODE
        ]
        assert names == sorted(names)
