"""confirmed_source_contributions : épinglage à l'attache admin, désépinglage au détachement."""

import pytest
from sqlalchemy import text

from application.services.contributions.assign_orphans import assign_orphan_contribution
from application.services.contributions.core import reject_pair
from application.services.persons.core import update_name_form_status
from domain.errors import PersonAlreadyInPublicationError
from infrastructure.repositories import contribution_repository, person_repository
from pipeline.transformation.publications.publication_perimeter import (
    PublicationPerimeterRecompute,
)
from tests.integration.helpers.contributions import insert_contribution
from tests.integration.helpers.groups import group_person, insert_group, set_perimeter_author_group
from tests.integration.helpers.persons import insert_person, insert_person_name_form
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record

_PERIMETER = PublicationPerimeterRecompute()


def _orphan_source_contribution(conn):
    """Publication + source_record + source_contribution orpheline, seul membre d'un groupe d'auteur du périmètre sans personne. Retourne (source_contribution_id, groupe, publication_id)."""
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
    group = insert_group(conn, publication, [(sa, source_record)])
    set_perimeter_author_group(conn, group)
    return sa, group, publication


def _pin(conn, source_contribution_id):
    return conn.execute(
        text(
            "SELECT person_id FROM confirmed_source_contributions WHERE source_contribution_id = :s"
        ),
        {"s": source_contribution_id},
    ).scalar_one_or_none()


def test_attach_pins(sa_sync_conn):
    pid = insert_person(sa_sync_conn, "Martin", first_name="Jean")
    sa, group, _publication = _orphan_source_contribution(sa_sync_conn)
    assign_orphan_contribution(
        pid,
        group,
        conn=sa_sync_conn,
        perimeter_recompute=_PERIMETER,
        repo=person_repository(sa_sync_conn),
        contribution_repo=contribution_repository(sa_sync_conn),
    )
    assert group_person(sa_sync_conn, group) == (pid, "manual")
    assert _pin(sa_sync_conn, sa) == pid


def test_detach_unpins(sa_sync_conn):
    pid = insert_person(sa_sync_conn, "Martin", first_name="Jean")
    sa, group, publication = _orphan_source_contribution(sa_sync_conn)
    assign_orphan_contribution(
        pid,
        group,
        conn=sa_sync_conn,
        perimeter_recompute=_PERIMETER,
        repo=person_repository(sa_sync_conn),
        contribution_repo=contribution_repository(sa_sync_conn),
    )
    assert _pin(sa_sync_conn, sa) == pid

    reject_pair(
        publication,
        pid,
        conn=sa_sync_conn,
        perimeter_recompute=_PERIMETER,
        repo=contribution_repository(sa_sync_conn),
    )
    assert _pin(sa_sync_conn, sa) is None
    assert group_person(sa_sync_conn, group) == (None, None)


def test_name_form_rejection_spares_pinned_groups(sa_sync_conn):
    """Rejeter une forme de nom détache les groupes rattachés par le nom sous cette forme, sauf ceux que l'admin a épinglés sur la personne."""
    pid = insert_person(sa_sync_conn, "Durand", first_name="Paul")
    pinned, pinned_group, _ = _orphan_source_contribution(sa_sync_conn)
    _, matched_group, _ = _orphan_source_contribution(sa_sync_conn)
    persons, contributions = person_repository(sa_sync_conn), contribution_repository(sa_sync_conn)
    assign_orphan_contribution(
        pid,
        pinned_group,
        conn=sa_sync_conn,
        perimeter_recompute=_PERIMETER,
        repo=persons,
        contribution_repo=contributions,
    )
    set_perimeter_author_group(sa_sync_conn, matched_group, person_id=pid, mode="name")
    insert_person_name_form(
        sa_sync_conn,
        pid,
        name_form="jean martin",
        sources=["hal"],
        status="pending",
        ignore_conflict=True,
    )

    update_name_form_status(
        pid,
        "jean martin",
        "rejected",
        conn=sa_sync_conn,
        perimeter_recompute=_PERIMETER,
        repo=persons,
        contribution_repo=contributions,
    )

    assert (group_person(sa_sync_conn, pinned_group), _pin(sa_sync_conn, pinned)) == (
        (pid, "manual"),
        pid,
    )
    assert group_person(sa_sync_conn, matched_group) == (None, None)


def test_attach_refuse_quand_la_personne_a_un_groupe_manuel_dans_la_publication(sa_sync_conn):
    pid = insert_person(sa_sync_conn, "Martin", first_name="Jean")
    _, group, publication = _orphan_source_contribution(sa_sync_conn)
    manual = insert_contribution(sa_sync_conn, publication, person_id=pid)

    with pytest.raises(PersonAlreadyInPublicationError) as error:
        assign_orphan_contribution(
            pid,
            group,
            conn=sa_sync_conn,
            perimeter_recompute=_PERIMETER,
            repo=person_repository(sa_sync_conn),
            contribution_repo=contribution_repository(sa_sync_conn),
        )
    assert error.value.contribution_id == manual
