"""Fusion des éditeurs qui sont un autre nom du titulaire de leurs préfixes DOI (`merge_duplicate_publishers`)."""

import logging

from sqlalchemy import text

from infrastructure.repositories.publisher_merge import merge_publisher_into
from pipeline.transformation.publishing.publishers.merge_duplicate_publishers import (
    find_publisher_aliases,
    run_merge_duplicate_publishers,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.serials import insert_doi_prefix, insert_publisher
from tests.integration.helpers.sources import insert_source_record


def _records(conn, prefix: str, publisher_id: int, count: int, *, start: int = 0) -> None:
    """Insère `count` publications à DOI de `prefix`, chacune avec un enregistrement source HAL qui nomme `publisher_id`."""
    for i in range(start, start + count):
        publication = insert_publication(conn, doi=f"{prefix}/x{i}")
        insert_source_record(
            conn,
            publication,
            source="hal",
            source_id=f"hal-{prefix}-{i}",
            publisher_id=publisher_id,
        )


def test_un_autre_nom_rejoint_le_titulaire_du_prefixe(sa_sync_conn):
    holder = insert_publisher(sa_sync_conn, "American Physical Society (APS)")
    named = insert_publisher(sa_sync_conn, "Amer Physical Soc")
    insert_doi_prefix(sa_sync_conn, "10.1103", ra="Crossref", publisher_id=holder)
    _records(sa_sync_conn, "10.1103", named, 5)

    run_merge_duplicate_publishers(
        sa_sync_conn,
        logging.getLogger("test"),
        merge=lambda target, source: merge_publisher_into(sa_sync_conn, target, source),
    )

    remaining = (
        sa_sync_conn.execute(
            text("SELECT id FROM publishers WHERE id IN (:a, :b)"), {"a": holder, "b": named}
        )
        .scalars()
        .all()
    )
    assert remaining == [holder]
    publishers = (
        sa_sync_conn.execute(
            text(
                "SELECT DISTINCT publisher_id FROM source_records WHERE source_id LIKE 'hal-10.1103-%'"
            )
        )
        .scalars()
        .all()
    )
    assert publishers == [holder]


def test_une_marque_reste_distincte(sa_sync_conn):
    holder = insert_publisher(sa_sync_conn, "Springer")
    brand = insert_publisher(sa_sync_conn, "BioMed Central")
    insert_doi_prefix(sa_sync_conn, "10.1186", ra="Crossref", publisher_id=holder)
    _records(sa_sync_conn, "10.1186", brand, 5)
    assert find_publisher_aliases(sa_sync_conn) == []


def test_trop_peu_d_enregistrements_ou_titulaires_partages(sa_sync_conn):
    holder = insert_publisher(sa_sync_conn, "Walter de Gruyter")
    other = insert_publisher(sa_sync_conn, "Brill")
    named = insert_publisher(sa_sync_conn, "De Gruyter")
    insert_doi_prefix(sa_sync_conn, "10.1515", ra="Crossref", publisher_id=holder)
    insert_doi_prefix(sa_sync_conn, "10.1163", ra="Crossref", publisher_id=other)
    _records(sa_sync_conn, "10.1515", named, 4)
    assert find_publisher_aliases(sa_sync_conn) == []
    _records(sa_sync_conn, "10.1163", named, 2)
    _records(sa_sync_conn, "10.1515", named, 2, start=4)
    # 6 enregistrements sources sur 8 chez le même titulaire : moins de 90 %.
    assert find_publisher_aliases(sa_sync_conn) == []


def test_un_prefixe_de_plateforme_ne_compte_pas(sa_sync_conn):
    platform = insert_publisher(sa_sync_conn, "OpenEdition")
    named = insert_publisher(sa_sync_conn, "OpenEdition Journals")
    insert_doi_prefix(sa_sync_conn, "10.4000", ra="Crossref", publisher_id=platform)
    _records(sa_sync_conn, "10.4000", named, 5)
    assert find_publisher_aliases(sa_sync_conn) == []
