"""Requêtes du script d'enrichissement du pays des éditeurs, sur la base de test."""

from unittest.mock import MagicMock

from sqlalchemy import text

from interfaces.cli.maintenance import enrich_publishers as module
from tests.integration.helpers.journals import insert_publisher


def _country(conn, publisher_id):
    return conn.execute(
        text("SELECT country FROM publishers WHERE id = :id"), {"id": publisher_id}
    ).scalar_one()


def test_find_countryless_rend_les_editeurs_openalex_sans_pays(sa_sync_conn):
    candidat = insert_publisher(sa_sync_conn, "A", openalex_id="P1")
    insert_publisher(sa_sync_conn, "B")
    pourvu = insert_publisher(sa_sync_conn, "C", openalex_id="P3")
    sa_sync_conn.execute(
        text("UPDATE publishers SET country = 'de' WHERE id = :id"), {"id": pourvu}
    )

    assert module.find_countryless(sa_sync_conn) == [(candidat, "P1")]
    assert module.find_countryless(sa_sync_conn, 0) == []


def test_le_pays_est_ecrit_seulement_la_ou_il_manque(sa_sync_conn, monkeypatch):
    candidat = insert_publisher(sa_sync_conn, "A", openalex_id="P1")
    monkeypatch.setattr(module.time, "sleep", lambda *_: None)
    # Commit neutralisé : la transaction du test est annulée à la fin.
    monkeypatch.setattr(sa_sync_conn, "commit", lambda: None)

    module.run_enrich_publishers_from_openalex(
        sa_sync_conn,
        MagicMock(),
        fetch_batch=lambda _ids: {"P1": "fr"},
    )
    assert _country(sa_sync_conn, candidat) == "fr"

    module.run_enrich_publishers_from_openalex(
        sa_sync_conn,
        MagicMock(),
        fetch_batch=lambda _ids: {"P1": "nl"},
    )
    assert _country(sa_sync_conn, candidat) == "fr"
