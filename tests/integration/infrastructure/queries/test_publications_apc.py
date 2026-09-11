"""Lignes APC de la liste des publications : `in_perimeter` suit la règle du filtre `has_apc`."""

from sqlalchemy import text

from application.ports.read_models.publications_queries import PublicationFilters
from infrastructure.read_models.publications.list import list_publications


def _structure(conn, code: str) -> int:
    return conn.execute(
        text(
            "INSERT INTO structures (code, name, structure_type) "
            "VALUES (:c, :c, 'universite') RETURNING id"
        ),
        {"c": code},
    ).scalar_one()


def test_apc_in_perimeter_follows_budget_structure(sa_sync_conn):
    inside = _structure(sa_sync_conn, "apc_inside")
    outside = _structure(sa_sync_conn, "apc_outside")
    pub_id = sa_sync_conn.execute(
        text(
            "INSERT INTO publications (title, pub_year, in_perimeter) "
            "VALUES ('APC', 2024, TRUE) RETURNING id"
        )
    ).scalar_one()
    for budget in (inside, outside, None):
        sa_sync_conn.execute(
            text(
                "INSERT INTO apc_payments (publication_id, amount_eur_ht, budget_structure_id) "
                "VALUES (:p, 100, :b)"
            ),
            {"p": pub_id, "b": budget},
        )

    response = list_publications(
        sa_sync_conn,
        filters=PublicationFilters(),
        perimeter_structure_ids=[inside],
        page=1,
        per_page=10,
        sort="year_desc",
    )

    item = next(p for p in response.publications if p.id == pub_id)
    assert item.apc is not None
    assert {a.budget_structure_id: a.in_perimeter for a in item.apc} == {
        inside: True,
        outside: False,
        None: False,
    }
