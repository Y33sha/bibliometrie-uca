"""Les détachements du repository des contributions retirent la personne et le mode de résolution de la contribution."""

from infrastructure.db.queues import Queue
from infrastructure.repositories import contribution_repository
from infrastructure.repositories.contribution_repository import detach_rejected_contributions
from tests.integration.helpers.alignment import contribution_person, insert_person_contribution
from tests.integration.helpers.persons import insert_person, insert_rejected_contribution
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.queues import queued
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record


def _contribution(conn, publication, person, *, mode):
    """Contribution d'une contribution source de forme « jean dupont », rattaché à la personne `person` par le mode `mode`."""
    source_record = insert_source_record(conn, publication, source_id=f"hal-detach-{publication}")
    source_contribution = insert_source_contribution(
        conn, source_record, author_name_normalized="jean dupont"
    )
    return insert_person_contribution(conn, source_contribution, person_id=person, mode=mode)


def test_detachement_d_une_paire_rejetee(sa_sync_conn):
    person = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
    publication = insert_publication(sa_sync_conn)
    contribution = _contribution(sa_sync_conn, publication, person, mode="orcid")
    insert_rejected_contribution(sa_sync_conn, publication, person_id=person)

    assert detach_rejected_contributions(sa_sync_conn, person) == 1

    assert contribution_person(sa_sync_conn, contribution) == (None, None)


def test_marquage_par_forme_de_nom(sa_sync_conn):
    person = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
    publication = insert_publication(sa_sync_conn)
    by_name = _contribution(sa_sync_conn, publication, person, mode="name")
    _contribution(sa_sync_conn, insert_publication(sa_sync_conn), person, mode="orcid")

    marked = contribution_repository(sa_sync_conn).mark_contributions_for_name_form(
        person, "jean dupont"
    )

    assert marked == 1
    assert queued(sa_sync_conn, Queue.CONTRIBUTION_RESOLUTION) == {by_name}
    assert contribution_person(sa_sync_conn, by_name) == (person, "name")
