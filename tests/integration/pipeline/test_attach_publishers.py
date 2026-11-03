"""Rattachement en lot des enregistrements sources à leur éditeur (`attach_publishers`)."""

import logging

from sqlalchemy import text

from infrastructure.db.queues import Queue
from pipeline.transformation.publishing.publishers.attach_publishers import run_attach_publishers
from pipeline.transformation.publishing.publishers.store import PublisherStore
from tests.integration.helpers.queues import clear, queued
from tests.integration.helpers.serials import insert_publisher
from tests.integration.helpers.sources import insert_source_record


def _publisher_of(conn, source_record_id: int) -> int | None:
    return conn.execute(
        text("SELECT publisher_id FROM source_records WHERE id = :id"), {"id": source_record_id}
    ).scalar_one()


def _attach(conn):
    return run_attach_publishers(conn, logging.getLogger("test"))


def test_un_nom_inconnu_cree_un_editeur_et_sa_forme(sa_sync_conn):
    record = insert_source_record(
        sa_sync_conn, source="crossref", source_id="10.1/a", biblio={"publisher": "Zeta Press Ltd"}
    )
    clear(sa_sync_conn, Queue.SOURCE_RECORD_KEYS)

    metrics = _attach(sa_sync_conn)

    publisher = _publisher_of(sa_sync_conn, record)
    assert publisher is not None
    assert PublisherStore(sa_sync_conn).find_publisher_by_name_form("zeta press") == publisher
    assert metrics.extras["publisher_created"] == 1
    assert record in queued(sa_sync_conn, Queue.SOURCE_RECORD_KEYS)


def test_l_identifiant_openalex_est_attribue_a_l_editeur_de_la_forme(sa_sync_conn):
    elsevier = insert_publisher(sa_sync_conn, "Elsevier")
    PublisherStore(sa_sync_conn).add_publisher_name_form(elsevier, "elsevier")
    record = insert_source_record(
        sa_sync_conn,
        source="openalex",
        source_id="W1",
        biblio={"publisher": "Elsevier BV", "publisher_openalex_id": "P4310320990"},
    )

    _attach(sa_sync_conn)

    assert _publisher_of(sa_sync_conn, record) == elsevier
    assert (
        sa_sync_conn.execute(
            text("SELECT openalex_id FROM publishers WHERE id = :id"), {"id": elsevier}
        ).scalar_one()
        == "P4310320990"
    )


def test_un_article_datacite_dans_une_revue_a_un_editeur(sa_sync_conn):
    record = insert_source_record(
        sa_sync_conn,
        source="datacite",
        source_id="10.9/a",
        doc_type="article",
        biblio={"publisher": "Copernicus", "journal": {"title": "Revue"}},
    )
    _attach(sa_sync_conn)
    assert _publisher_of(sa_sync_conn, record) is not None


def test_un_article_datacite_sans_conteneur_est_heberge_par_un_entrepot(sa_sync_conn):
    zenodo = insert_publisher(sa_sync_conn, "Zenodo")
    record = insert_source_record(
        sa_sync_conn,
        source="datacite",
        source_id="10.5281/zenodo.1",
        doc_type="article",
        publisher_id=zenodo,
        biblio={"publisher": "Zenodo"},
    )

    metrics = _attach(sa_sync_conn)

    assert _publisher_of(sa_sync_conn, record) is None
    assert metrics.extras["publishers_detached"] == 1


def test_un_jeu_de_donnees_est_sans_editeur(sa_sync_conn):
    record = insert_source_record(
        sa_sync_conn,
        source="datacite",
        source_id="10.9/b",
        doc_type="dataset",
        biblio={"publisher": "Copernicus", "journal": {"title": "Revue"}},
    )
    _attach(sa_sync_conn)
    assert _publisher_of(sa_sync_conn, record) is None


def test_le_type_d_avant_correction_decide(sa_sync_conn):
    """Une correction du type par `metadata_correction` n'est pas une décision de la source."""
    record = insert_source_record(
        sa_sync_conn,
        source="crossref",
        source_id="10.1/c",
        doc_type="preprint",
        corrections={"doc_type": {"raw": "article", "corrected_by": "regle"}},
        biblio={"publisher": "Elsevier"},
    )
    _attach(sa_sync_conn)
    assert _publisher_of(sa_sync_conn, record) is not None


def test_un_second_passage_ne_change_rien(sa_sync_conn):
    record = insert_source_record(
        sa_sync_conn, source="crossref", source_id="10.1/a", biblio={"publisher": "Zeta Press"}
    )
    _attach(sa_sync_conn)
    clear(sa_sync_conn, Queue.SOURCE_RECORD_KEYS)

    metrics = _attach(sa_sync_conn)

    assert metrics.updated == 0
    assert metrics.extras.get("publisher_created", 0) == 0
    assert record not in queued(sa_sync_conn, Queue.SOURCE_RECORD_KEYS)
