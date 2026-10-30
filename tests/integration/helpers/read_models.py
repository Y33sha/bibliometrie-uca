"""Lectures de l'API construites sur la connexion d'un test."""

from sqlalchemy import Connection

from infrastructure.read_models.publications.queries import PublicationsQueries


def _no_extra_connection() -> Connection:
    raise AssertionError("le test fournit une seule connexion")


def publications_queries(conn: Connection) -> PublicationsQueries:
    """Renvoie les lectures des publications sur `conn`. Le calcul parallèle des facettes, qui ouvre d'autres connexions, lève `AssertionError`."""
    return PublicationsQueries(conn, open_connection=_no_extra_connection)
