"""Tests d'intégration pour `infrastructure.queries.api.countries`."""

from sqlalchemy import text

from domain.countries import NO_COUNTRY_CODE
from infrastructure.queries.api.countries import PgCountriesQueries


def _ensure_country(conn, code, name="Test"):
    conn.execute(
        text("INSERT INTO countries (code, name) VALUES (:c, :n) ON CONFLICT DO NOTHING"),
        {"c": code, "n": name},
    )


class TestListCountries:
    def test_puts_the_absence_of_country_first(self, sa_sync_conn):
        """L'absence de pays ouvre la liste : c'est l'arbitrage le plus fréquent, et le seul qui ne se cherche pas par son nom."""
        _ensure_country(sa_sync_conn, "FR", "France")
        _ensure_country(sa_sync_conn, NO_COUNTRY_CODE, "Non applicable")

        codes = [r.code.strip() for r in PgCountriesQueries(sa_sync_conn).list_countries()]
        assert codes[0] == NO_COUNTRY_CODE
        assert "FR" in codes

    def test_sorts_the_rest_by_name(self, sa_sync_conn):
        _ensure_country(sa_sync_conn, "ZA", "Afrique du Sud")
        _ensure_country(sa_sync_conn, "FR", "France")

        names = [
            r.name
            for r in PgCountriesQueries(sa_sync_conn).list_countries()
            if r.code.strip() != NO_COUNTRY_CODE
        ]
        assert names == sorted(names)
