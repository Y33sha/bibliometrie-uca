"""confirmed_authorships : épinglage à l'attache admin, désépinglage au détachement,
réapplication (enforce) côté pipeline.
"""

from sqlalchemy import text

from application.authorships.assign_orphans import assign_orphan_authorship
from application.authorships.core import reject_pair
from infrastructure.repositories import authorship_repository, person_repository
from tests.integration.helpers.authorships import upsert_identity


def _person(conn, last="Martin", first="Jean"):
    return conn.execute(
        text(
            "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
            "VALUES (:l, :f, lower(:l), lower(:f)) RETURNING id"
        ),
        {"l": last, "f": first},
    ).scalar_one()


def _orphan_sa(conn):
    """Publication + source_publication + source_authorship orpheline. Retourne (sa_id, pub_id)."""
    pub = conn.execute(
        text("INSERT INTO publications (title, pub_year) VALUES ('t', 2024) RETURNING id")
    ).scalar_one()
    sp = conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, publication_id) "
            "VALUES ('hal', :sid, 't', :p) RETURNING id"
        ),
        {"sid": f"hal-{pub}", "p": pub},
    ).scalar_one()
    identity = upsert_identity(conn, "jean martin", None)
    sa = conn.execute(
        text(
            "INSERT INTO source_authorships (source, source_publication_id, author_position, "
            "person_id, in_perimeter, raw_author_name, identity_id) "
            "VALUES ('hal', :sp, 0, NULL, TRUE, 'Jean Martin', :iid) RETURNING id"
        ),
        {"sp": sp, "iid": identity},
    ).scalar_one()
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
    pid = _person(sa_sync_conn)
    sa, _pub = _orphan_sa(sa_sync_conn)
    assign_orphan_authorship(
        pid,
        "hal",
        sa,
        repo=person_repository(sa_sync_conn),
        authorship_repo=authorship_repository(sa_sync_conn),
    )
    assert _sa_person(sa_sync_conn, sa) == pid
    assert _pin(sa_sync_conn, sa) == pid


def test_detach_unpins(sa_sync_conn):
    pid = _person(sa_sync_conn)
    sa, pub = _orphan_sa(sa_sync_conn)
    assign_orphan_authorship(
        pid,
        "hal",
        sa,
        repo=person_repository(sa_sync_conn),
        authorship_repo=authorship_repository(sa_sync_conn),
    )
    assert _pin(sa_sync_conn, sa) == pid

    reject_pair(pub, pid, repo=authorship_repository(sa_sync_conn))
    assert _pin(sa_sync_conn, sa) is None
    assert _sa_person(sa_sync_conn, sa) is None


def test_enforce_restores_pinned_signature(sa_sync_conn):
    pid = _person(sa_sync_conn)
    sa, _pub = _orphan_sa(sa_sync_conn)
    repo = authorship_repository(sa_sync_conn)
    repo.pin_authorships([sa], pid)
    # Une opération quelconque détache la signature sans retirer l'épinglage.
    sa_sync_conn.execute(
        text("UPDATE source_authorships SET person_id = NULL WHERE id = :s"), {"s": sa}
    )
    assert _sa_person(sa_sync_conn, sa) is None

    assert repo.enforce_confirmed_authorships() == 1
    assert _sa_person(sa_sync_conn, sa) == pid
