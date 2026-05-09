"""Tests d'intégration pour `infrastructure.db.queries.persons.admin`."""

import json

from sqlalchemy import text

from infrastructure.db.queries.persons.admin import (
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


def _create_sp(
    conn,
    source="hal",
    source_id="sp1",
    person_id=None,
    full_name="X",
    hal_person_id=None,
    idhal=None,
    orcid=None,
):
    source_ids: dict = {}
    if hal_person_id is not None:
        source_ids["hal_person_id"] = hal_person_id
    if idhal:
        source_ids["idhal"] = idhal
    row = conn.execute(
        text(
            "INSERT INTO source_persons "
            "(source, source_id, full_name, person_id, source_ids, orcid) "
            "VALUES (:src, :sid, :fn, :pid, CAST(:ids AS jsonb), :orcid) RETURNING id"
        ),
        {
            "src": source,
            "sid": source_id,
            "fn": full_name,
            "pid": person_id,
            "ids": json.dumps(source_ids) if source_ids else None,
            "orcid": orcid,
        },
    ).one()
    return row.id


def _create_sa(
    conn,
    sd,
    sp,
    *,
    source="hal",
    person_id=None,
    in_perimeter=True,
    excluded=False,
    author_name_normalized=None,
    raw_author_name="X",
):
    row = conn.execute(
        text("""
            INSERT INTO source_authorships
                (source, source_publication_id, source_person_id, author_position,
                 person_id, in_perimeter, excluded, author_name_normalized, raw_author_name)
            VALUES (:src, :sd, :sp, 0, :pid, :inp, :excl, :anf, :raw) RETURNING id
        """),
        {
            "src": source,
            "sd": sd,
            "sp": sp,
            "pid": person_id,
            "inp": in_perimeter,
            "excl": excluded,
            "anf": author_name_normalized,
            "raw": raw_author_name,
        },
    ).one()
    return row.id


class TestOrphanAuthorshipsCount:
    def test_counts_orphans(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        sp = _create_sp(sa_sync_conn)
        _create_sa(sa_sync_conn, sd, sp, person_id=None)  # orpheline
        sp2 = _create_sp(sa_sync_conn, source_id="sp2")
        pid = _create_person(sa_sync_conn)
        _create_sa(sa_sync_conn, sd, sp2, person_id=pid)  # attribuée

        count = orphan_authorships_count(sa_sync_conn)
        assert count["total"] >= 1

    def test_excludes_non_uca(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        sp = _create_sp(sa_sync_conn)
        _create_sa(sa_sync_conn, sd, sp, person_id=None, in_perimeter=False)
        count = orphan_authorships_count(sa_sync_conn)
        assert count["total"] == 0

    def test_excludes_memoir(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn, doc_type="memoir")
        sd = _create_sd(sa_sync_conn, pub)
        sp = _create_sp(sa_sync_conn)
        _create_sa(sa_sync_conn, sd, sp, person_id=None)
        count = orphan_authorships_count(sa_sync_conn)
        assert count["total"] == 0


class TestListOrphanAuthorships:
    def test_lists_orphan_authorships(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        sp = _create_sp(sa_sync_conn, full_name="Dupond Jean")
        sa = _create_sa(sa_sync_conn, sd, sp, person_id=None, raw_author_name="Dupond Jean")

        res = list_orphan_authorships(sa_sync_conn, search="", page=1, per_page=50)
        assert res["total"] >= 1
        assert any(a["authorship_id"] == sa for a in res["authorships"])

    def test_filters_by_search(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        sp1 = _create_sp(sa_sync_conn, source_id="sp-m", full_name="SpecialName")
        sp2 = _create_sp(sa_sync_conn, source_id="sp-o", full_name="Autre")
        sa_match = _create_sa(sa_sync_conn, sd, sp1, person_id=None, raw_author_name="SpecialName")
        _create_sa(sa_sync_conn, sd, sp2, person_id=None, raw_author_name="Autre")

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
        sp = _create_sp(sa_sync_conn)
        _create_sa(sa_sync_conn, sd, sp, person_id=pid, author_name_normalized="dupond j")
        sa_sync_conn.execute(
            text("INSERT INTO person_name_forms (name_form, person_ids) VALUES ('dupond j', :ids)"),
            {"ids": [pid, other]},
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
        sp = _create_sp(sa_sync_conn)
        _create_sa(sa_sync_conn, sd, sp, person_id=pid, author_name_normalized="x")
        assert name_form_remaining_authorships(sa_sync_conn, pid, "x") == 1
        assert name_form_remaining_authorships(sa_sync_conn, pid, "autre") == 0


# Tests pour `hal_duplicate_accounts` déplacés vers
# `tests/integration/infrastructure/db/queries/test_hal_problems.py` —
# la query est maintenant exposée par PgHalProblemsQueries.
