"""Phase personnes : une signature copiée dans la liste d'auteurs de sa notice (`duplicate_of`) n'est rattachée à personne."""

from sqlalchemy import text

from pipeline.transformation.persons.loading import fetch_unlinked_contributions
from pipeline.transformation.persons.persons import detach_copies
from tests.integration.helpers.contributions import insert_confirmed_source_contribution
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_signature, insert_source_record


def _original_and_copy(conn, source_id, *, person_id=None):
    """Signature d'origine et sa copie dans la même notice, du périmètre."""
    notice = insert_source_record(conn, insert_publication(conn), source_id=source_id)
    original, copy = (
        insert_signature(
            conn,
            notice,
            author_position=position,
            raw_author_name="Jean Martin",
            author_name_normalized="jean martin",
            in_perimeter=True,
            person_id=person_id,
            resolution_mode="name" if person_id else None,
        )
        for position in (0, 3)
    )
    conn.execute(
        text("UPDATE source_contributions SET duplicate_of = :o WHERE id = :c"),
        {"o": original, "c": copy},
    )
    return original, copy


def _person(conn, signature):
    return conn.execute(
        text("SELECT person_id FROM source_contributions WHERE id = :s"), {"s": signature}
    ).scalar_one()


def test_une_copie_n_est_pas_a_rattacher(sa_sync_conn):
    original, copy = _original_and_copy(sa_sync_conn, "hal-1")

    unlinked = {a.source_contribution_id for a in fetch_unlinked_contributions(sa_sync_conn)}

    assert original in unlinked
    assert copy not in unlinked


def test_une_copie_rattachee_perd_sa_personne_sauf_epinglage(sa_sync_conn):
    conn = sa_sync_conn
    person = insert_person(conn, "Martin", first_name="Jean")
    original, copy = _original_and_copy(conn, "hal-1", person_id=person)
    _, pinned = _original_and_copy(conn, "hal-2", person_id=person)
    insert_confirmed_source_contribution(conn, pinned, person_id=person)

    assert detach_copies(conn) == 1

    assert (_person(conn, original), _person(conn, copy), _person(conn, pinned)) == (
        person,
        None,
        person,
    )
