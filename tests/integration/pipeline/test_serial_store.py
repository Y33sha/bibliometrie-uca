"""Recherche ou création des revues (`SerialStore`)."""

import pytest
from sqlalchemy import text

from domain.normalize import normalize_text
from pipeline.transformation.publishing.serials.store import SerialStore
from tests.integration.helpers.serials import insert_publisher


@pytest.fixture
def gateway(sa_sync_conn):
    return SerialStore(sa_sync_conn)


def _fetch_one(conn, sql_text: str, **params):
    """Exécute un SELECT et renvoie sa première ligne, ou `None`."""
    return conn.execute(text(sql_text), params).first()


class TestSerialStore:
    def test_revue_creee_avec_son_titre_normalise(self, sa_sync_conn, gateway):
        serial_id = gateway.create_serial("REVUE & SOCIÉTÉ")
        row = _fetch_one(
            sa_sync_conn, "SELECT title, title_normalized FROM serials WHERE id = :id", id=serial_id
        )
        assert tuple(row) == ("REVUE & SOCIÉTÉ", normalize_text("REVUE & SOCIÉTÉ"))

    def test_revue_sans_issn_d_un_titre(self, sa_sync_conn, gateway):
        serial_id = gateway.serial_for_title("REVUE & SOCIÉTÉ")
        assert gateway.serial_for_title("Revue & Société") == serial_id

    def test_revue_sans_issn_d_un_titre_et_d_un_editeur(self, sa_sync_conn, gateway):
        elsevier = insert_publisher(sa_sync_conn, "Elsevier")
        serial_id = gateway.serial_for_title_and_publisher("REVUE & SOCIÉTÉ", elsevier)
        assert gateway.serial_for_title_and_publisher("Revue & Société", elsevier) == serial_id
        assert gateway.serial_for_title_and_publisher("Revue & Société", None) != serial_id

    def test_une_revue_a_issn_n_est_pas_la_revue_sans_issn_de_son_titre(
        self, sa_sync_conn, gateway
    ):
        with_issn = gateway.create_serial("Nature")
        sa_sync_conn.execute(
            text("INSERT INTO serial_issns (issn, serial_id) VALUES ('0028-0836', :id)"),
            {"id": with_issn},
        )
        assert gateway.serial_for_title("Nature") != with_issn
