"""Tests d'intégration de `PgDoiPrefixesQueries` (requêtes contre le schéma réel)."""

from __future__ import annotations

from sqlalchemy import text

from infrastructure.pipeline.doi_prefixes import PgDoiPrefixesQueries


def test_breakdown_by_registration_agency_s_execute(sa_sync_conn):
    """La requête (jointure `candidate_dois` × `doi_prefixes`) est valide contre le
    schéma ; sur une base vide elle renvoie une liste (vide)."""
    repo = PgDoiPrefixesQueries(sa_sync_conn)
    result = repo.breakdown_by_registration_agency()
    assert result == []


def _row(conn, prefix):
    return conn.execute(
        text("SELECT ra, publisher_checked_at FROM doi_prefixes WHERE prefix = :p"),
        {"p": prefix},
    ).one()


def test_prefixes_to_resolve_include_unknown_ones(sa_sync_conn):
    sa_sync_conn.execute(
        text(
            "INSERT INTO doi_prefixes (prefix, ra) VALUES "
            "('10.1007', 'unknown'), ('10.1016', 'Crossref')"
        )
    )
    assert PgDoiPrefixesQueries(sa_sync_conn).get_prefixes_to_resolve() == ["10.1007"]


def test_save_ra_reclassifies_unknown_and_keeps_known(sa_sync_conn):
    sa_sync_conn.execute(
        text(
            "INSERT INTO doi_prefixes (prefix, ra, publisher_checked_at) VALUES "
            "('10.1007', 'unknown', now()), ('10.1016', 'Crossref', now())"
        )
    )
    repo = PgDoiPrefixesQueries(sa_sync_conn)

    assert repo.save_ra(prefix="10.1007", ra="Crossref") is True
    assert tuple(_row(sa_sync_conn, "10.1007")) == ("Crossref", None)
    assert repo.save_ra(prefix="10.1016", ra="DataCite") is False
    assert _row(sa_sync_conn, "10.1016").ra == "Crossref"
    assert repo.save_ra(prefix="10.5281", ra="DataCite") is True
    assert _row(sa_sync_conn, "10.5281").ra == "DataCite"


def test_save_ra_leaves_unknown_prefix_untouched(sa_sync_conn):
    sa_sync_conn.execute(
        text(
            "INSERT INTO doi_prefixes (prefix, ra, publisher_checked_at) "
            "VALUES ('10.99999', 'unknown', now())"
        )
    )
    repo = PgDoiPrefixesQueries(sa_sync_conn)

    assert repo.save_ra(prefix="10.99999", ra="unknown") is False
    assert _row(sa_sync_conn, "10.99999").publisher_checked_at is not None
