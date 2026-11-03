"""Éditeur d'une revue calculé d'après ses publications (`serial_publishers`)."""

from sqlalchemy import text

from pipeline.transformation.publishing.serials.serial_publishers import (
    refresh_serial_publishers,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.serials import insert_monograph, insert_publisher, insert_serial


def _publications(conn, serial_id: int, publisher_id: int, year: int, n: int = 1) -> None:
    for _ in range(n):
        publication = insert_publication(conn, serial_id=serial_id, publication_year=year)
        conn.execute(
            text("UPDATE publications SET publisher_id = :p WHERE id = :id"),
            {"p": publisher_id, "id": publication},
        )


def _publisher_of(conn, serial_id: int) -> int | None:
    return conn.execute(
        text("SELECT publisher_id FROM serials WHERE id = :id"), {"id": serial_id}
    ).scalar_one()


def test_l_editeur_de_la_derniere_annee_l_emporte(sa_sync_conn):
    """*animal* : Cambridge jusqu'en 2020, Elsevier ensuite."""
    cambridge = insert_publisher(sa_sync_conn, "Cambridge")
    elsevier = insert_publisher(sa_sync_conn, "Elsevier")
    serial = insert_serial(sa_sync_conn, "animal", publisher_id=cambridge)
    _publications(sa_sync_conn, serial, cambridge, 2019, n=5)
    _publications(sa_sync_conn, serial, elsevier, 2023)

    assert refresh_serial_publishers(sa_sync_conn) >= 1
    assert _publisher_of(sa_sync_conn, serial) == elsevier
    assert refresh_serial_publishers(sa_sync_conn) == 0


def test_a_egalite_le_plus_frequent_sur_toutes_les_annees(sa_sync_conn):
    first = insert_publisher(sa_sync_conn, "A")
    second = insert_publisher(sa_sync_conn, "B")
    serial = insert_serial(sa_sync_conn, "Revue")
    _publications(sa_sync_conn, serial, second, 2020, n=3)
    _publications(sa_sync_conn, serial, first, 2023)
    _publications(sa_sync_conn, serial, second, 2023)

    refresh_serial_publishers(sa_sync_conn, serial)

    assert _publisher_of(sa_sync_conn, serial) == second


def test_une_collection_garde_l_editeur_des_publications_de_ses_monographies(sa_sync_conn):
    """Une collection sans ISSN est trouvée par son titre et son éditeur : sans éditeur, elle serait recréée au run suivant."""
    publisher = insert_publisher(sa_sync_conn, "RILEM")
    collection = insert_serial(sa_sync_conn, "Proceedings of ICBBM", publisher_id=publisher)
    monograph = insert_monograph(
        sa_sync_conn, "Proceedings of ICBBM 2025", publisher_id=publisher, serial_id=collection
    )
    insert_publication(sa_sync_conn, monograph_id=monograph, publisher_id=publisher)

    assert refresh_serial_publishers(sa_sync_conn) == 0
    assert _publisher_of(sa_sync_conn, collection) == publisher


def test_une_publication_de_la_revue_et_de_sa_monographie_compte_une_fois(sa_sync_conn):
    first = insert_publisher(sa_sync_conn, "A")
    second = insert_publisher(sa_sync_conn, "B")
    serial = insert_serial(sa_sync_conn, "Collection")
    monograph = insert_monograph(sa_sync_conn, "Volume", serial_id=serial)
    insert_publication(sa_sync_conn, serial_id=serial, monograph_id=monograph, publisher_id=second)
    insert_publication(sa_sync_conn, serial_id=serial, publisher_id=first)

    refresh_serial_publishers(sa_sync_conn, serial)

    # Une voix chacun : le plus petit identifiant départage.
    assert _publisher_of(sa_sync_conn, serial) == first


def test_sans_publication_a_editeur_la_revue_n_en_a_pas(sa_sync_conn):
    publisher = insert_publisher(sa_sync_conn, "A")
    serial = insert_serial(sa_sync_conn, "Revue", publisher_id=publisher)
    insert_publication(sa_sync_conn, serial_id=serial)

    refresh_serial_publishers(sa_sync_conn)

    assert _publisher_of(sa_sync_conn, serial) is None
