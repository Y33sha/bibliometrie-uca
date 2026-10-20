"""Oneshot `clear_detached_resolution_modes` : mode de résolution des signatures sans personne."""

from sqlalchemy import text

from interfaces.cli.oneshot.clear_detached_resolution_modes import clear
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_signature, insert_source_record


def test_seules_les_signatures_sans_personne_perdent_leur_mode(sa_sync_conn):
    notice = insert_source_record(sa_sync_conn, insert_publication(sa_sync_conn))
    person = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
    detached = insert_signature(
        sa_sync_conn, notice, author_position=0, resolution_mode="identifier"
    )
    linked = insert_signature(
        sa_sync_conn, notice, author_position=1, person_id=person, resolution_mode="identifier"
    )

    clear(sa_sync_conn)

    modes = dict(
        sa_sync_conn.execute(
            text("SELECT id, resolution_mode::text FROM source_contributions WHERE id IN (:a, :b)"),
            {"a": detached, "b": linked},
        ).all()
    )
    assert modes == {detached: None, linked: "identifier"}
