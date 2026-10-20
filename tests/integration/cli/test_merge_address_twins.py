"""Fusion des adresses de même forme normalisée."""

import pytest
from sqlalchemy import text

from interfaces.cli.oneshot.merge_address_twins import StaleNormalizedTextError, merge
from tests.integration.helpers.addresses import insert_address, insert_address_structure
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import (
    insert_signature,
    insert_signature_address,
    insert_source_record,
)
from tests.integration.helpers.structures import insert_structure


@pytest.fixture
def sa_sync_conn(sa_sync_conn_owner):
    """Stock d'avant l'unicité des formes normalisées : index et contrainte retirés dans la transaction du test, que le rollback rétablit."""
    sa_sync_conn_owner.execute(
        text(
            "DROP INDEX structures.addresses_normalized_text_key;"
            " ALTER TABLE structures.addresses"
            " DROP CONSTRAINT ck_addresses_normalized_text_not_empty"
        )
    )
    return sa_sync_conn_owner


def _signature(conn, source_id):
    return insert_signature(
        conn, insert_source_record(conn, insert_publication(conn, "P"), source_id=source_id)
    )


def _addresses(conn):
    return conn.execute(text("SELECT id, countries FROM addresses ORDER BY id")).all()


def test_les_jumelles_rejoignent_l_adresse_la_plus_citee(sa_sync_conn):
    rare = insert_address(
        sa_sync_conn,
        "Univ. Lyon, France",
        normalized_text="univ lyon france",
        countries=["fr"],
        publication_count=1,
    )
    frequent = insert_address(
        sa_sync_conn,
        "Univ Lyon France",
        normalized_text="univ lyon france",
        countries=["it"],
        publication_count=5,
    )
    sa1, sa2 = _signature(sa_sync_conn, "h1"), _signature(sa_sync_conn, "h2")
    insert_signature_address(sa_sync_conn, sa1, address_id=rare)
    insert_signature_address(sa_sync_conn, sa2, address_id=frequent)
    sa_sync_conn.execute(
        text("INSERT INTO source_contribution_rors VALUES (:sa, 'https://ror.org/x', :a)"),
        {"sa": sa1, "a": rare},
    )

    merge(sa_sync_conn)

    ((kept, countries),) = _addresses(sa_sync_conn)
    assert kept == frequent
    assert sorted(countries) == ["fr", "it"]
    linked = sa_sync_conn.execute(
        text(
            "SELECT source_contribution_id FROM source_contribution_addresses WHERE address_id = :a"
        ),
        {"a": frequent},
    ).scalars()
    assert set(linked) == {sa1, sa2}
    ror_address = sa_sync_conn.execute(
        text("SELECT address_id FROM source_contribution_rors WHERE source_contribution_id = :sa"),
        {"sa": sa1},
    ).scalar_one()
    assert ror_address == frequent


def test_des_decisions_opposees_redeviennent_a_examiner(sa_sync_conn):
    structure = insert_structure(sa_sync_conn)
    a = insert_address(sa_sync_conn, "Labo X", normalized_text="labo x", publication_count=2)
    b = insert_address(sa_sync_conn, "LABO X", normalized_text="labo x", publication_count=1)
    insert_address_structure(sa_sync_conn, a, structure_id=structure, is_confirmed=True)
    insert_address_structure(sa_sync_conn, b, structure_id=structure, is_confirmed=False)

    merge(sa_sync_conn)

    assert sa_sync_conn.execute(
        text("SELECT address_id, is_confirmed FROM address_structures")
    ).all() == [(a, None)]


def test_une_decision_d_une_jumelle_passe_a_l_adresse_gardee(sa_sync_conn):
    structure = insert_structure(sa_sync_conn)
    kept = insert_address(sa_sync_conn, "Labo Y", normalized_text="labo y", publication_count=2)
    twin = insert_address(sa_sync_conn, "LABO Y", normalized_text="labo y", publication_count=1)
    insert_address_structure(sa_sync_conn, kept, structure_id=structure)
    insert_address_structure(sa_sync_conn, twin, structure_id=structure, is_confirmed=False)

    merge(sa_sync_conn)

    assert sa_sync_conn.execute(
        text("SELECT address_id, is_confirmed FROM address_structures")
    ).all() == [(kept, False)]


def test_les_formes_vides_sont_supprimees(sa_sync_conn):
    insert_address(sa_sync_conn, ";", normalized_text="")
    merge(sa_sync_conn)
    assert _addresses(sa_sync_conn) == []


def test_refuse_des_formes_perimees(sa_sync_conn):
    insert_address(sa_sync_conn, "R&D, Lyon", normalized_text="r amp d lyon")
    with pytest.raises(StaleNormalizedTextError):
        merge(sa_sync_conn)
