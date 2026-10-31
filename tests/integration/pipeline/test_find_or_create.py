"""Recherche ou création des éditeurs (`pipeline/transformation/publishing/find_or_create.py`) et des revues (`SerialStore`)."""

import pytest
from sqlalchemy import text

from pipeline.transformation.publishing.find_or_create import find_or_create_publisher
from pipeline.transformation.publishing.publishers.store import PublisherStore
from pipeline.transformation.publishing.serials.store import SerialStore
from tests.integration.helpers.serials import insert_publisher


@pytest.fixture
def gateway(sa_sync_conn):
    return SerialStore(sa_sync_conn)


@pytest.fixture
def publisher_store(sa_sync_conn):
    return PublisherStore(sa_sync_conn)


def _fetch_one(conn, sql_text: str, **params):
    """Exécute un SELECT et renvoie sa première ligne, ou `None`."""
    return conn.execute(text(sql_text), params).first()


class TestFindOrCreatePublisher:
    def test_returns_none_on_empty_name(self, sa_sync_conn, publisher_store):
        assert find_or_create_publisher(None, repo=publisher_store) is None
        assert find_or_create_publisher("", repo=publisher_store) is None

    def test_creates_new_publisher(self, sa_sync_conn, publisher_store):
        publisher_id = find_or_create_publisher("Elsevier", repo=publisher_store)
        assert publisher_id is not None
        row = _fetch_one(
            sa_sync_conn, "SELECT name FROM publishers WHERE id = :id", id=publisher_id
        )
        assert row.name == "Elsevier"

    def test_finds_existing_by_openalex_id(self, sa_sync_conn, publisher_store):
        existing = insert_publisher(sa_sync_conn, "Elsevier", openalex_id="P4310310871")
        found = find_or_create_publisher(
            "Elsevier BV", openalex_id="P4310310871", repo=publisher_store
        )
        assert found == existing

    def test_un_nom_encode_rejoint_le_meme_editeur_que_le_nom_en_clair(
        self, sa_sync_conn, publisher_store
    ):
        """Un nom avec entités HTML (`&amp;`) rejoint l'éditeur du nom en clair."""
        premier = find_or_create_publisher("Taylor & Francis", repo=publisher_store)
        second = find_or_create_publisher("TAYLOR &amp; FRANCIS", repo=publisher_store)
        assert second == premier

    def test_finds_existing_by_name_form(self, sa_sync_conn, publisher_store):
        existing = find_or_create_publisher("Elsevier", repo=publisher_store)
        found = find_or_create_publisher("elsevier", repo=publisher_store)
        assert found == existing

    def test_variantes_de_nom_rejoignent_le_meme_editeur(self, sa_sync_conn, publisher_store):
        """Les formes juridiques, dates et « on behalf of » ajoutés par les sources n'empêchent pas de retrouver l'éditeur."""
        elsevier = find_or_create_publisher("Elsevier BV", repo=publisher_store)
        for variant in (
            "Elsevier [1977-....]",
            "Elsevier Ltd.",
            "Elsevier on behalf of the American College of Cardiology Foundation",
        ):
            assert find_or_create_publisher(variant, repo=publisher_store) == elsevier
        row = _fetch_one(sa_sync_conn, "SELECT name FROM publishers WHERE id = :id", id=elsevier)
        assert row.name == "Elsevier BV"

    def test_attaches_openalex_id_if_missing(self, sa_sync_conn, publisher_store):
        existing = find_or_create_publisher("Elsevier", repo=publisher_store)
        find_or_create_publisher("Elsevier", openalex_id="P123", repo=publisher_store)
        row = _fetch_one(
            sa_sync_conn, "SELECT openalex_id FROM publishers WHERE id = :id", id=existing
        )
        assert row.openalex_id == "P123"


class TestSerialStore:
    def test_revue_d_un_issn_l_creee_puis_retrouvee(self, sa_sync_conn, gateway):
        serial_id = gateway.serial_for_issnl("0028-0836", "Nature")
        assert gateway.serial_for_issnl("0028-0836", "Autre titre") == serial_id
        row = _fetch_one(
            sa_sync_conn,
            "SELECT s.title, i.serial_id FROM serials s JOIN serial_issns i ON i.serial_id = s.id "
            "WHERE i.issn = '0028-0836'",
        )
        assert tuple(row) == ("Nature", serial_id)

    def test_revue_sans_issn_d_un_titre_et_d_un_editeur(self, sa_sync_conn, gateway):
        elsevier = insert_publisher(sa_sync_conn, "Elsevier")
        serial_id = gateway.serial_for_title("Revue &amp; Société", elsevier)
        assert gateway.serial_for_title("Revue & Société", elsevier) == serial_id
        assert gateway.serial_for_title("Revue & Société", None) != serial_id

    def test_une_revue_a_issn_n_est_pas_la_revue_sans_issn_de_son_titre(
        self, sa_sync_conn, gateway
    ):
        with_issn = gateway.serial_for_issnl("0028-0836", "Nature")
        assert gateway.serial_for_title("Nature", None) != with_issn

    def test_titre_saisi_a_la_main_garde(self, sa_sync_conn, gateway):
        serial_id = gateway.serial_for_issnl("0028-0836", "Nature")
        gateway.set_title(serial_id, "Nature (London)")
        title = "SELECT title FROM serials WHERE id = :id"
        assert _fetch_one(sa_sync_conn, title, id=serial_id).title == "Nature (London)"
        sa_sync_conn.execute(
            text("UPDATE serials SET manual_fields = ARRAY['title'] WHERE id = :id"),
            {"id": serial_id},
        )
        gateway.set_title(serial_id, "Nature")
        assert _fetch_one(sa_sync_conn, title, id=serial_id).title == "Nature (London)"
