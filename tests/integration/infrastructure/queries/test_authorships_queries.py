"""Tests d'intégration pour `infrastructure.queries.api.authorships`."""

from sqlalchemy import text

from infrastructure.queries.api.authorships import (
    list_orphan_authorships,
    orphan_authorships_count,
)
from tests.integration.helpers.authorships import upsert_identity


def _create_person(conn, last="A", first="Z"):
    return conn.execute(
        text(
            "INSERT INTO persons "
            "(last_name, first_name, last_name_normalized, first_name_normalized) "
            "VALUES (:l, :f, lower(:l), lower(:f)) RETURNING id"
        ),
        {"l": last, "f": first},
    ).scalar_one()


def _create_pub(conn):
    return conn.execute(
        text(
            "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
            "VALUES ('X', 'x', 2024, 'article') RETURNING id"
        )
    ).scalar_one()


def _create_sd(conn, pub_id, source="hal", source_id="h1"):
    return conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, publication_id) "
            "VALUES (:src, :sid, 'X', :pid) RETURNING id"
        ),
        {"src": source, "sid": source_id, "pid": pub_id},
    ).scalar_one()


def _create_sa(
    conn,
    sd,
    *,
    source="hal",
    author_position=0,
    person_id=None,
    in_perimeter=True,
    raw_author_name="X",
    roles=None,
):
    identity_id = upsert_identity(conn, author_name_normalized=None)
    return conn.execute(
        text("""
            INSERT INTO source_authorships
                (source, source_publication_id, author_position,
                 person_id, in_perimeter, identity_id, raw_author_name, roles)
            VALUES (:src, :sd, :pos, :pid, :inp, :iid, :raw,
                    COALESCE(:roles, ARRAY['author']::text[]))
            RETURNING id
        """),
        {
            "src": source,
            "sd": sd,
            "pos": author_position,
            "pid": person_id,
            "inp": in_perimeter,
            "iid": identity_id,
            "raw": raw_author_name,
            "roles": roles,
        },
    ).scalar_one()


class TestOrphanAuthorshipsCount:
    def test_counts_orphans(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        _create_sa(sa_sync_conn, sd, author_position=0, person_id=None)  # orpheline
        pid = _create_person(sa_sync_conn)
        _create_sa(sa_sync_conn, sd, author_position=1, person_id=pid)  # attribuée

        assert orphan_authorships_count(sa_sync_conn).total >= 1

    def test_excludes_out_of_perimeter(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        _create_sa(sa_sync_conn, sd, person_id=None, in_perimeter=False)
        assert orphan_authorships_count(sa_sync_conn).total == 0

    def test_excludes_non_author_roles(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub, source="theses", source_id="t1")
        _create_sa(sa_sync_conn, sd, source="theses", person_id=None, roles=["thesis_director"])
        _create_sa(
            sa_sync_conn,
            sd,
            source="theses",
            author_position=1,
            person_id=None,
            roles=["jury_member"],
        )
        assert orphan_authorships_count(sa_sync_conn).total == 0


class TestListOrphanAuthorships:
    def test_lists_orphan_authorships(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        sa = _create_sa(sa_sync_conn, sd, person_id=None, raw_author_name="Dupond Jean")

        res = list_orphan_authorships(sa_sync_conn, search="", page=1, per_page=50)
        assert res.total >= 1
        assert any(a.source_authorship_id == sa for a in res.authorships)

    def test_filters_by_search(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        sa_match = _create_sa(
            sa_sync_conn, sd, author_position=0, person_id=None, raw_author_name="SpecialName"
        )
        _create_sa(sa_sync_conn, sd, author_position=1, person_id=None, raw_author_name="Autre")

        res = list_orphan_authorships(sa_sync_conn, search="Special", page=1, per_page=50)
        assert sa_match in [a.source_authorship_id for a in res.authorships]
