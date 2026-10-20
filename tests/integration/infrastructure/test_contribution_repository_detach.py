"""Les détachements du repository des contributions retirent la personne et le mode de résolution de la signature."""

from sqlalchemy import text

from infrastructure.repositories import contribution_repository
from infrastructure.repositories.contribution_repository import detach_rejected_signatures
from tests.integration.helpers.persons import insert_person, insert_rejected_contribution
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_signature, insert_source_record


def _signature(conn, publication, person, *, name="jean dupont"):
    notice = insert_source_record(conn, publication, source_id=f"hal-detach-{publication}")
    return insert_signature(
        conn,
        notice,
        author_name_normalized=name,
        person_id=person,
        resolution_mode="identifier",
    )


def _link(conn, signature):
    return tuple(
        conn.execute(
            text("SELECT person_id, resolution_mode FROM source_contributions WHERE id = :id"),
            {"id": signature},
        ).one()
    )


def test_detachement_d_une_paire_rejetee(sa_sync_conn):
    person = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
    publication = insert_publication(sa_sync_conn)
    signature = _signature(sa_sync_conn, publication, person)
    insert_rejected_contribution(sa_sync_conn, publication, person_id=person)

    detach_rejected_signatures(sa_sync_conn, person)

    assert _link(sa_sync_conn, signature) == (None, None)


def test_detachement_par_forme_de_nom(sa_sync_conn):
    person = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
    signature = _signature(sa_sync_conn, insert_publication(sa_sync_conn), person)

    contribution_repository(sa_sync_conn).null_person_id_for_name_form(person, "jean dupont")

    assert _link(sa_sync_conn, signature) == (None, None)
