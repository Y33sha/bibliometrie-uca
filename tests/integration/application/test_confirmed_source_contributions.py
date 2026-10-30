"""Épinglage des contributions sources à la personne (`confirmed_source_contributions`) au rattachement manuel, désépinglage au détachement."""

import pytest
from sqlalchemy import text

from application.services.contributions import reject_pair
from domain.errors import PersonAlreadyInPublicationError
from infrastructure.db.queues import Queue
from infrastructure.repositories import contribution_repository
from interfaces.api.deps import contribution_service, person_service
from pipeline.transformation.publications.publication_perimeter import (
    PublicationPerimeterRecompute,
)
from tests.integration.helpers.alignment import (
    align_source_contributions,
    contribution_person,
    set_perimeter_author_contribution,
)
from tests.integration.helpers.contributions import insert_contribution
from tests.integration.helpers.persons import insert_person, insert_person_name_form
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.queues import queued
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record


def _orphan_source_contribution(conn):
    """Insère une contribution source, seule dans une contribution d'auteur du périmètre sans personne. Renvoie (contribution source, contribution, publication)."""
    publication = insert_publication(conn, "t", normalize_title=False, doc_type=None)
    source_record = insert_source_record(
        conn, publication, source_id=f"hal-{publication}", title="t"
    )
    sa = insert_source_contribution(
        conn,
        source_record,
        in_perimeter=True,
        raw_author_name="Jean Martin",
        author_name_normalized="jean martin",
    )
    contribution = align_source_contributions(conn, publication, [(sa, source_record)])
    set_perimeter_author_contribution(conn, contribution)
    return sa, contribution, publication


def _pin(conn, source_contribution_id):
    return conn.execute(
        text(
            "SELECT person_id FROM confirmed_source_contributions WHERE source_contribution_id = :s"
        ),
        {"s": source_contribution_id},
    ).scalar_one_or_none()


def test_attach_pins(sa_sync_conn):
    pid = insert_person(sa_sync_conn, "Martin", first_name="Jean")
    sa, contribution, _publication = _orphan_source_contribution(sa_sync_conn)
    contribution_service(sa_sync_conn).assign_orphan_contribution(pid, contribution)
    assert contribution_person(sa_sync_conn, contribution) == (pid, "manual")
    assert _pin(sa_sync_conn, sa) == pid


def test_detach_unpins(sa_sync_conn):
    pid = insert_person(sa_sync_conn, "Martin", first_name="Jean")
    sa, contribution, publication = _orphan_source_contribution(sa_sync_conn)
    contribution_service(sa_sync_conn).assign_orphan_contribution(pid, contribution)
    assert _pin(sa_sync_conn, sa) == pid

    reject_pair(
        publication,
        pid,
        perimeter_recompute=PublicationPerimeterRecompute(sa_sync_conn),
        repo=contribution_repository(sa_sync_conn),
    )
    assert _pin(sa_sync_conn, sa) is None
    assert contribution_person(sa_sync_conn, contribution) == (None, None)


def test_name_form_rejection_spares_pinned_contributions(sa_sync_conn):
    """Rejeter une forme de nom met en file de résolution les contributions rattachées par le nom sous cette forme, sauf celles épinglées sur la personne par un rattachement manuel."""
    pid = insert_person(sa_sync_conn, "Durand", first_name="Paul")
    pinned, pinned_contribution, _ = _orphan_source_contribution(sa_sync_conn)
    _, matched_contribution, _ = _orphan_source_contribution(sa_sync_conn)
    contribution_service(sa_sync_conn).assign_orphan_contribution(pid, pinned_contribution)
    set_perimeter_author_contribution(
        sa_sync_conn, matched_contribution, person_id=pid, mode="name"
    )
    insert_person_name_form(
        sa_sync_conn,
        pid,
        name_form="jean martin",
        sources=["hal"],
        status="pending",
        ignore_conflict=True,
    )

    person_service(sa_sync_conn).update_name_form_status(pid, "jean martin", "rejected")

    assert (contribution_person(sa_sync_conn, pinned_contribution), _pin(sa_sync_conn, pinned)) == (
        (pid, "manual"),
        pid,
    )
    assert queued(sa_sync_conn, Queue.CONTRIBUTION_RESOLUTION) == {matched_contribution}


def test_attach_refuse_quand_la_personne_a_une_contribution_manuelle_dans_la_publication(
    sa_sync_conn,
):
    pid = insert_person(sa_sync_conn, "Martin", first_name="Jean")
    _, contribution, publication = _orphan_source_contribution(sa_sync_conn)
    manual = insert_contribution(sa_sync_conn, publication, person_id=pid)

    with pytest.raises(PersonAlreadyInPublicationError) as error:
        contribution_service(sa_sync_conn).assign_orphan_contribution(pid, contribution)
    assert error.value.contribution_id == manual
    assert str(error.value) == "Cette personne est déjà rattachée à cette publication."
