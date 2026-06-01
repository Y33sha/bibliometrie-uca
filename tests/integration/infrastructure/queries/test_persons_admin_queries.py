"""Tests d'intégration pour `infrastructure.queries.persons.admin`."""

from sqlalchemy import text

from infrastructure.queries.persons.admin import (
    list_orphan_authorships,
    name_form_authorships,
    name_form_remaining_authorships,
    orphan_authorships_count,
    person_exists,
)


def _create_person(conn, last="A", first="Z", rejected=False):
    row = conn.execute(
        text(
            "INSERT INTO persons "
            "(last_name, first_name, last_name_normalized, first_name_normalized, rejected) "
            "VALUES (:l, :f, lower(:l), lower(:f), :r) RETURNING id"
        ),
        {"l": last, "f": first, "r": rejected},
    ).one()
    return row.id


def _create_pub(conn, doc_type="article"):
    row = conn.execute(
        text(
            "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
            "VALUES ('X', 'x', 2024, CAST(:dt AS doc_type)) RETURNING id"
        ),
        {"dt": doc_type},
    ).one()
    return row.id


def _create_sd(conn, pub_id, source="hal", source_id="h1"):
    row = conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, publication_id) "
            "VALUES (:src, :sid, 'X', :pid) RETURNING id"
        ),
        {"src": source, "sid": source_id, "pid": pub_id},
    ).one()
    return row.id


def _create_sa(
    conn,
    sd,
    *,
    source="hal",
    author_position=0,
    person_id=None,
    in_perimeter=True,
    author_name_normalized=None,
    raw_author_name="X",
    roles=None,
):
    row = conn.execute(
        text("""
            INSERT INTO source_authorships
                (source, source_publication_id, author_position,
                 person_id, in_perimeter, author_name_normalized, raw_author_name,
                 roles)
            VALUES (:src, :sd, :pos, :pid, :inp, :anf, :raw,
                    COALESCE(:roles, ARRAY['author']::text[]))
            RETURNING id
        """),
        {
            "src": source,
            "sd": sd,
            "pos": author_position,
            "pid": person_id,
            "inp": in_perimeter,
            "anf": author_name_normalized,
            "raw": raw_author_name,
            "roles": roles,
        },
    ).one()
    return row.id


class TestOrphanAuthorshipsCount:
    def test_counts_orphans(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        _create_sa(sa_sync_conn, sd, author_position=0, person_id=None)  # orpheline
        pid = _create_person(sa_sync_conn)
        _create_sa(sa_sync_conn, sd, author_position=1, person_id=pid)  # attribuée

        count = orphan_authorships_count(sa_sync_conn)
        assert count["total"] >= 1

    def test_excludes_non_uca(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        _create_sa(sa_sync_conn, sd, person_id=None, in_perimeter=False)
        count = orphan_authorships_count(sa_sync_conn)
        assert count["total"] == 0

    def test_excludes_memoir(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn, doc_type="memoir")
        sd = _create_sd(sa_sync_conn, pub)
        _create_sa(sa_sync_conn, sd, person_id=None)
        count = orphan_authorships_count(sa_sync_conn)
        assert count["total"] == 0

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
        count = orphan_authorships_count(sa_sync_conn)
        assert count["total"] == 0


class TestListOrphanAuthorships:
    def test_lists_orphan_authorships(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        sa = _create_sa(sa_sync_conn, sd, person_id=None, raw_author_name="Dupond Jean")

        res = list_orphan_authorships(sa_sync_conn, search="", page=1, per_page=50)
        assert res["total"] >= 1
        assert any(a["authorship_id"] == sa for a in res["authorships"])

    def test_filters_by_search(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        sa_match = _create_sa(
            sa_sync_conn, sd, author_position=0, person_id=None, raw_author_name="SpecialName"
        )
        _create_sa(sa_sync_conn, sd, author_position=1, person_id=None, raw_author_name="Autre")

        res = list_orphan_authorships(sa_sync_conn, search="Special", page=1, per_page=50)
        ids = [a["authorship_id"] for a in res["authorships"]]
        assert sa_match in ids


class TestPersonExists:
    def test_true_when_exists(self, sa_sync_conn):
        pid = _create_person(sa_sync_conn)
        assert person_exists(sa_sync_conn, pid) is True

    def test_false_when_missing(self, sa_sync_conn):
        assert person_exists(sa_sync_conn, 999_999) is False


class TestNameFormAuthorships:
    def test_returns_authorships_and_other_persons(self, sa_sync_conn):
        pid = _create_person(sa_sync_conn, last="Dupond")
        other = _create_person(sa_sync_conn, last="Martin")
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        _create_sa(sa_sync_conn, sd, person_id=pid, author_name_normalized="dupond j")
        sa_sync_conn.execute(
            text(
                "INSERT INTO person_name_forms (name_form, person_id, sources) "
                "VALUES ('dupond j', :pid, ARRAY['hal']), "
                "       ('dupond j', :other, ARRAY['hal'])"
            ),
            {"pid": pid, "other": other},
        )

        res = name_form_authorships(sa_sync_conn, pid, "dupond j")
        assert len(res["authorships"]) >= 1
        other_ids = [p["id"] for p in res["other_persons"]]
        assert other in other_ids


class TestNameFormRemainingAuthorships:
    def test_counts_remaining(self, sa_sync_conn):
        pid = _create_person(sa_sync_conn)
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        _create_sa(sa_sync_conn, sd, person_id=pid, author_name_normalized="x")
        assert name_form_remaining_authorships(sa_sync_conn, pid, "x") == 1
        assert name_form_remaining_authorships(sa_sync_conn, pid, "autre") == 0


# Tests pour `hal_duplicate_accounts` déplacés vers
# `tests/integration/infrastructure/queries/test_hal_problems.py` —
# la query est maintenant exposée par PgHalProblemsQueries.
