"""Nettoyage des adresses orphelines, en fin de phase `normalize`."""

from sqlalchemy import text

from pipeline.ingestion.common.signature_queries import delete_orphan_addresses
from tests.integration.helpers.addresses import insert_address, insert_address_structure
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import (
    insert_signature,
    insert_signature_address,
    insert_source_publication,
)
from tests.integration.helpers.structures import insert_structure


def _address_ids(conn) -> set[int]:
    return set(conn.execute(text("SELECT id FROM addresses")).scalars())


def test_seules_les_adresses_sans_signature_sont_supprimees(sa_sync_conn):
    pub_id = insert_publication(sa_sync_conn, "P")
    sa_id = insert_signature(sa_sync_conn, insert_source_publication(sa_sync_conn, pub_id))
    liee = insert_address(sa_sync_conn, "Adresse liée")
    insert_signature_address(sa_sync_conn, sa_id, address_id=liee)
    insert_address(sa_sync_conn, "Adresse orpheline")

    assert delete_orphan_addresses(sa_sync_conn) == 1
    assert _address_ids(sa_sync_conn) == {liee}


def test_une_orpheline_part_avec_ses_liens_aux_structures_meme_confirmes(sa_sync_conn):
    orpheline = insert_address(sa_sync_conn, "Adresse orpheline")
    insert_address_structure(
        sa_sync_conn, orpheline, structure_id=insert_structure(sa_sync_conn), is_confirmed=True
    )

    assert delete_orphan_addresses(sa_sync_conn) == 1
    assert sa_sync_conn.execute(text("SELECT count(*) FROM address_structures")).scalar_one() == 0
