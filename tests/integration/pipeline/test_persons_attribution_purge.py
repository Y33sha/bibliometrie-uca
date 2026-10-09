"""Purge des attributions d'identifiant automatiques qu'aucune signature de leur personne ne porte."""

from functools import partial

from sqlalchemy import text

from infrastructure.pipeline.persons.matching import PgPersonsMatchingQueries
from tests.integration.helpers.persons import insert_person, insert_person_identifier
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_signature, insert_source_publication

_ORCID = "0000-0001-2345-6789"


# Attribution de l'ORCID du module.
_attribution = partial(insert_person_identifier, id_type="orcid", id_value=_ORCID)


def _signature(conn, person_id, name, *, neutralized=None):
    pub = insert_publication(conn, "t")
    sp = insert_source_publication(conn, pub, source_id=f"hal-{pub}", title="t")
    insert_signature(
        conn,
        sp,
        raw_author_name=name,
        author_name_normalized=name,
        person_identifiers={"orcid": _ORCID},
        person_id=person_id,
        in_perimeter=True,
        resolution_mode="name",
        neutralized_identifiers=neutralized,
    )


def _attribution_remaining(conn, person_id):
    return conn.execute(
        text("SELECT EXISTS (SELECT 1 FROM person_identifiers WHERE person_id = :pid)"),
        {"pid": person_id},
    ).scalar_one()


def test_attribution_automatique_sans_signature_supprimee(sa_sync_conn):
    person = insert_person(sa_sync_conn, "Monteil", first_name="Jean")
    _attribution(sa_sync_conn, person)
    assert PgPersonsMatchingQueries().delete_unsupported_identifier_attributions(sa_sync_conn) >= 1
    assert not _attribution_remaining(sa_sync_conn, person)


def test_signature_qui_neutralise_l_identifiant_ne_le_porte_pas(sa_sync_conn):
    person = insert_person(sa_sync_conn, "Monteil", first_name="Jean")
    _attribution(sa_sync_conn, person)
    _signature(sa_sync_conn, person, "monteil jean", neutralized={"orcid": "misplaced"})
    PgPersonsMatchingQueries().delete_unsupported_identifier_attributions(sa_sync_conn)
    assert not _attribution_remaining(sa_sync_conn, person)


def test_attribution_portee_par_une_signature_conservee(sa_sync_conn):
    person = insert_person(sa_sync_conn, "Monteil", first_name="Jean")
    _attribution(sa_sync_conn, person)
    _signature(sa_sync_conn, person, "monteil jean")
    PgPersonsMatchingQueries().delete_unsupported_identifier_attributions(sa_sync_conn)
    assert _attribution_remaining(sa_sync_conn, person)


def test_attribution_confirmee_conservee(sa_sync_conn):
    person = insert_person(sa_sync_conn, "Monteil", first_name="Jean")
    _attribution(sa_sync_conn, person, status="confirmed")
    PgPersonsMatchingQueries().delete_unsupported_identifier_attributions(sa_sync_conn)
    assert _attribution_remaining(sa_sync_conn, person)


def test_attribution_manuelle_conservee(sa_sync_conn):
    person = insert_person(sa_sync_conn, "Monteil", first_name="Jean")
    _attribution(sa_sync_conn, person, source="manual")
    PgPersonsMatchingQueries().delete_unsupported_identifier_attributions(sa_sync_conn)
    assert _attribution_remaining(sa_sync_conn, person)
