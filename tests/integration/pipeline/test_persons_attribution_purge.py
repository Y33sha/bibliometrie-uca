"""Purge des attributions d'identifiant automatiques qu'aucune contribution source des contributions de leur personne ne contient."""

from functools import partial

from sqlalchemy import text

from pipeline.transformation.persons.purge import delete_unsupported_identifier_attributions
from tests.integration.helpers.alignment import insert_person_contribution
from tests.integration.helpers.persons import insert_person, insert_person_identifier
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record

_ORCID = "0000-0001-2345-6789"


# Attribution de l'ORCID du module.
_attribution = partial(insert_person_identifier, id_type="orcid", id_value=_ORCID)


def _source_contribution(conn, person_id, name, *, neutralized=None):
    publication = insert_publication(conn, "t")
    source_record = insert_source_record(
        conn, publication, source_id=f"hal-{publication}", title="t"
    )
    source_contribution = insert_source_contribution(
        conn,
        source_record,
        raw_author_name=name,
        author_name_normalized=name,
        identifiers={"orcid": _ORCID},
        in_perimeter=True,
        neutralized_identifiers=neutralized,
    )
    insert_person_contribution(conn, source_contribution, person_id=person_id)


def _attribution_remaining(conn, person_id):
    return conn.execute(
        text("SELECT EXISTS (SELECT 1 FROM person_identifiers WHERE person_id = :pid)"),
        {"pid": person_id},
    ).scalar_one()


def test_attribution_automatique_sans_contribution_source_alignee_supprimee(sa_sync_conn):
    person = insert_person(sa_sync_conn, "Monteil", first_name="Jean")
    _attribution(sa_sync_conn, person)
    assert delete_unsupported_identifier_attributions(sa_sync_conn) >= 1
    assert not _attribution_remaining(sa_sync_conn, person)


def test_contribution_source_qui_neutralise_l_identifiant_ne_le_porte_pas(sa_sync_conn):
    person = insert_person(sa_sync_conn, "Monteil", first_name="Jean")
    _attribution(sa_sync_conn, person)
    _source_contribution(sa_sync_conn, person, "monteil jean", neutralized={"orcid": "misplaced"})
    delete_unsupported_identifier_attributions(sa_sync_conn)
    assert not _attribution_remaining(sa_sync_conn, person)


def test_attribution_portee_par_une_contribution_source_alignee_conservee(sa_sync_conn):
    person = insert_person(sa_sync_conn, "Monteil", first_name="Jean")
    _attribution(sa_sync_conn, person)
    _source_contribution(sa_sync_conn, person, "monteil jean")
    delete_unsupported_identifier_attributions(sa_sync_conn)
    assert _attribution_remaining(sa_sync_conn, person)


def test_attribution_confirmee_conservee(sa_sync_conn):
    person = insert_person(sa_sync_conn, "Monteil", first_name="Jean")
    _attribution(sa_sync_conn, person, status="confirmed")
    delete_unsupported_identifier_attributions(sa_sync_conn)
    assert _attribution_remaining(sa_sync_conn, person)


def test_attribution_manuelle_conservee(sa_sync_conn):
    person = insert_person(sa_sync_conn, "Monteil", first_name="Jean")
    _attribution(sa_sync_conn, person, source="manual")
    delete_unsupported_identifier_attributions(sa_sync_conn)
    assert _attribution_remaining(sa_sync_conn, person)


def test_contribution_source_hors_contribution_ne_porte_pas_l_attribution(sa_sync_conn):
    """Une contribution source rattachée à la personne, hors de ses contributions, ne compte pas."""
    conn = sa_sync_conn
    person = insert_person(conn, "Monteil", first_name="Jean")
    _attribution(conn, person)
    source_record = insert_source_record(conn, insert_publication(conn, "t"), source_id="hal-x")
    insert_source_contribution(
        conn,
        source_record,
        raw_author_name="monteil jean",
        author_name_normalized="monteil jean",
        identifiers={"orcid": _ORCID},
    )
    delete_unsupported_identifier_attributions(conn)
    assert not _attribution_remaining(conn, person)
