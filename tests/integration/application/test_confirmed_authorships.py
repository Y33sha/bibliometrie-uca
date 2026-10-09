"""confirmed_authorships : épinglage à l'attache admin, désépinglage au détachement,
réapplication (enforce) côté pipeline.
"""

from sqlalchemy import text

from application.services.authorships.assign_orphans import assign_orphan_authorship
from application.services.authorships.core import reject_pair
from application.services.persons.core import update_name_form_status
from infrastructure.repositories import authorship_repository, person_repository
from tests.integration.helpers.persons import insert_person, insert_person_name_form
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_signature, insert_source_publication


def _orphan_sa(conn):
    """Publication + source_publication + source_authorship orpheline. Retourne (sa_id, pub_id)."""
    pub = insert_publication(conn, "t", normalize_title=False, doc_type=None)
    sp = insert_source_publication(conn, pub, source_id=f"hal-{pub}", title="t")
    sa = insert_signature(
        conn,
        sp,
        in_perimeter=True,
        raw_author_name="Jean Martin",
        author_name_normalized="jean martin",
    )
    return sa, pub


def _pin(conn, sa_id):
    return conn.execute(
        text("SELECT person_id FROM confirmed_authorships WHERE source_authorship_id = :s"),
        {"s": sa_id},
    ).scalar_one_or_none()


def _sa_person(conn, sa_id):
    return conn.execute(
        text("SELECT person_id FROM source_authorships WHERE id = :s"), {"s": sa_id}
    ).scalar_one()


def test_attach_pins(sa_sync_conn):
    pid = insert_person(sa_sync_conn, "Martin", first_name="Jean")
    sa, _pub = _orphan_sa(sa_sync_conn)
    assign_orphan_authorship(
        pid,
        sa,
        repo=person_repository(sa_sync_conn),
        authorship_repo=authorship_repository(sa_sync_conn),
    )
    assert _sa_person(sa_sync_conn, sa) == pid
    assert _pin(sa_sync_conn, sa) == pid


def test_detach_unpins(sa_sync_conn):
    pid = insert_person(sa_sync_conn, "Martin", first_name="Jean")
    sa, pub = _orphan_sa(sa_sync_conn)
    assign_orphan_authorship(
        pid,
        sa,
        repo=person_repository(sa_sync_conn),
        authorship_repo=authorship_repository(sa_sync_conn),
    )
    assert _pin(sa_sync_conn, sa) == pid

    reject_pair(pub, pid, repo=authorship_repository(sa_sync_conn))
    assert _pin(sa_sync_conn, sa) is None
    assert _sa_person(sa_sync_conn, sa) is None


def test_name_form_rejection_spares_pinned_signatures(sa_sync_conn):
    """Rejeter une forme de nom détache les signatures qui la portent, sauf celles que l'admin a épinglées sur la personne."""
    pid = insert_person(sa_sync_conn, "Durand", first_name="Paul")
    pinned, _ = _orphan_sa(sa_sync_conn)
    matched, _ = _orphan_sa(sa_sync_conn)
    persons, authorships = person_repository(sa_sync_conn), authorship_repository(sa_sync_conn)
    assign_orphan_authorship(pid, pinned, repo=persons, authorship_repo=authorships)
    sa_sync_conn.execute(
        text("UPDATE source_authorships SET person_id = :p WHERE id = :s"), {"p": pid, "s": matched}
    )
    insert_person_name_form(
        sa_sync_conn,
        pid,
        name_form="jean martin",
        sources=["hal"],
        status="pending",
        ignore_conflict=True,
    )

    update_name_form_status(
        pid, "jean martin", "rejected", repo=persons, authorship_repo=authorships
    )

    assert (_sa_person(sa_sync_conn, pinned), _pin(sa_sync_conn, pinned)) == (pid, pid)
    assert _sa_person(sa_sync_conn, matched) is None


def test_enforce_restores_pinned_signature(sa_sync_conn):
    pid = insert_person(sa_sync_conn, "Martin", first_name="Jean")
    sa, _pub = _orphan_sa(sa_sync_conn)
    repo = authorship_repository(sa_sync_conn)
    repo.pin_authorships([sa], pid)
    # Une opération quelconque détache la signature sans retirer l'épinglage.
    sa_sync_conn.execute(
        text("UPDATE source_authorships SET person_id = NULL WHERE id = :s"), {"s": sa}
    )
    assert _sa_person(sa_sync_conn, sa) is None

    from infrastructure.pipeline.persons.matching import PgPersonsMatchingQueries

    assert PgPersonsMatchingQueries().enforce_confirmed_authorships(sa_sync_conn) == 1
    assert _sa_person(sa_sync_conn, sa) == pid
