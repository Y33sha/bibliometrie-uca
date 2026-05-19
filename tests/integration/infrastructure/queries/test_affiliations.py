"""Tests d'intégration pour `infrastructure.queries.affiliations`."""

from infrastructure.queries.affiliations import (
    set_in_perimeter_from_addresses,
    set_structure_ids_from_addresses,
)


class TestSetInPerimeterFromAddressesDailyClause:
    """Régression : la branche `daily=True` injectait un JOIN directement
    après SET dans un UPDATE, ce qui n'est pas légal en PostgreSQL et
    cassait le pipeline (`psycopg.errors.SyntaxError`). On vérifie ici
    que le SQL parse maintenant correctement (peu importe combien de
    lignes sont mises à jour, c'est la syntaxe qu'on teste)."""

    def test_daily_true_does_not_raise(self, sa_sync_conn):
        # Aucune donnée requise : si le SQL parse, la fonction retourne 0.
        n = set_in_perimeter_from_addresses(
            sa_sync_conn, source="openalex", perimeter_ids=[1, 2, 3], daily=True
        )
        assert n == 0

    def test_daily_false_does_not_raise(self, sa_sync_conn):
        n = set_in_perimeter_from_addresses(
            sa_sync_conn, source="openalex", perimeter_ids=[1, 2, 3], daily=False
        )
        assert n == 0


class TestSetStructureIdsFromAddressesDailyClause:
    def test_daily_true_does_not_raise(self, sa_sync_conn):
        n = set_structure_ids_from_addresses(
            sa_sync_conn, source="openalex", wide_ids=[1, 2, 3], daily=True
        )
        assert n == 0

    def test_daily_false_does_not_raise(self, sa_sync_conn):
        n = set_structure_ids_from_addresses(
            sa_sync_conn, source="openalex", wide_ids=[1, 2, 3], daily=False
        )
        assert n == 0
