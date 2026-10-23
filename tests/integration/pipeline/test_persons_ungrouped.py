"""Phase personnes : une contribution source hors groupe n'est rattachée à personne."""

from sqlalchemy import text

from pipeline.transformation.persons.loading import fetch_unlinked_contributions
from pipeline.transformation.persons.persons import detach_ungrouped
from tests.integration.helpers.contributions import insert_confirmed_source_contribution
from tests.integration.helpers.groups import insert_group
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record


def _grouped_and_ungrouped(conn, source_id, *, person_id=None):
    """Deux contributions sources du périmètre d'un même enregistrement source : la première dans un groupe, la seconde hors groupe."""
    publication = insert_publication(conn)
    source_record = insert_source_record(conn, publication, source_id=source_id)
    grouped, ungrouped = (
        insert_source_contribution(
            conn,
            source_record,
            author_position=position,
            raw_author_name="Jean Martin",
            author_name_normalized="jean martin",
            in_perimeter=True,
            person_id=person_id,
            resolution_mode="name" if person_id else None,
        )
        for position in (0, 3)
    )
    insert_group(conn, publication, [(grouped, source_record)])
    return grouped, ungrouped


def _person(conn, source_contribution):
    return conn.execute(
        text("SELECT person_id FROM source_contributions WHERE id = :s"), {"s": source_contribution}
    ).scalar_one()


def test_une_contribution_source_hors_groupe_n_est_pas_a_rattacher(sa_sync_conn):
    grouped, ungrouped = _grouped_and_ungrouped(sa_sync_conn, "hal-1")

    unlinked = {a.source_contribution_id for a in fetch_unlinked_contributions(sa_sync_conn)}

    assert grouped in unlinked
    assert ungrouped not in unlinked


def test_une_contribution_source_hors_groupe_perd_sa_personne_sauf_epinglage(sa_sync_conn):
    conn = sa_sync_conn
    person = insert_person(conn, "Martin", first_name="Jean")
    grouped, ungrouped = _grouped_and_ungrouped(conn, "hal-1", person_id=person)
    _, pinned = _grouped_and_ungrouped(conn, "hal-2", person_id=person)
    insert_confirmed_source_contribution(conn, pinned, person_id=person)

    assert detach_ungrouped(conn) == 1

    assert (_person(conn, grouped), _person(conn, ungrouped), _person(conn, pinned)) == (
        person,
        None,
        person,
    )
