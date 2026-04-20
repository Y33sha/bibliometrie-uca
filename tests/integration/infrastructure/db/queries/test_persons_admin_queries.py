"""Tests d'intégration pour `infrastructure.db.queries.persons.admin`."""

import json

from infrastructure.db.queries.persons.admin import (
    hal_duplicate_accounts,
    list_orphan_authorships,
    name_form_authorships,
    name_form_remaining_authorships,
    orphan_authorships_count,
    person_exists,
)


def _create_person(db, last="A", first="Z", rejected=False):
    db.execute(
        "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized, rejected) "
        "VALUES (%s, %s, lower(%s), lower(%s), %s) RETURNING id",
        (last, first, last, first, rejected),
    )
    return db.fetchone()["id"]


def _create_pub(db, doc_type="article"):
    db.execute(
        "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
        "VALUES ('X', 'x', 2024, %s::doc_type) RETURNING id",
        (doc_type,),
    )
    return db.fetchone()["id"]


def _create_sd(db, pub_id, source="hal", source_id="h1"):
    db.execute(
        "INSERT INTO source_publications (source, source_id, title, publication_id) "
        "VALUES (%s, %s, 'X', %s) RETURNING id",
        (source, source_id, pub_id),
    )
    return db.fetchone()["id"]


def _create_sp(
    db, source="hal", source_id="sp1", person_id=None, full_name="X", hal_person_id=None, idhal=None, orcid=None
):
    source_ids = {}
    if hal_person_id is not None:
        source_ids["hal_person_id"] = hal_person_id
    if idhal:
        source_ids["idhal"] = idhal
    db.execute(
        """
        INSERT INTO source_persons (source, source_id, full_name, person_id, source_ids, orcid)
        VALUES (%s, %s, %s, %s, %s::jsonb, %s) RETURNING id
        """,
        (source, source_id, full_name, person_id, json.dumps(source_ids) if source_ids else None, orcid),
    )
    return db.fetchone()["id"]


def _create_sa(
    db,
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
    db.execute(
        """
        INSERT INTO source_authorships
            (source, source_publication_id, source_person_id, author_position,
             person_id, in_perimeter, excluded, author_name_normalized, raw_author_name)
        VALUES (%s, %s, %s, 0, %s, %s, %s, %s, %s) RETURNING id
        """,
        (
            source,
            sd,
            sp,
            person_id,
            in_perimeter,
            excluded,
            author_name_normalized,
            raw_author_name,
        ),
    )
    return db.fetchone()["id"]


class TestOrphanAuthorshipsCount:
    def test_counts_orphans(self, db):
        pub = _create_pub(db)
        sd = _create_sd(db, pub)
        sp = _create_sp(db)
        _create_sa(db, sd, sp, person_id=None)  # orpheline
        _create_sa(
            db, sd, _create_sp(db, source_id="sp2"), person_id=_create_person(db)
        )  # attribuée

        count = orphan_authorships_count(db)
        assert count["total"] >= 1

    def test_excludes_non_uca(self, db):
        pub = _create_pub(db)
        sd = _create_sd(db, pub)
        sp = _create_sp(db)
        _create_sa(db, sd, sp, person_id=None, in_perimeter=False)
        count = orphan_authorships_count(db)
        assert count["total"] == 0

    def test_excludes_memoir(self, db):
        pub = _create_pub(db, doc_type="memoir")
        sd = _create_sd(db, pub)
        sp = _create_sp(db)
        _create_sa(db, sd, sp, person_id=None)
        count = orphan_authorships_count(db)
        assert count["total"] == 0


class TestListOrphanAuthorships:
    def test_lists_orphan_authorships(self, db):
        pub = _create_pub(db)
        sd = _create_sd(db, pub)
        sp = _create_sp(db, full_name="Dupond Jean")
        sa = _create_sa(db, sd, sp, person_id=None, raw_author_name="Dupond Jean")

        res = list_orphan_authorships(db, search="", page=1, per_page=50)
        assert res["total"] >= 1
        assert any(a["authorship_id"] == sa for a in res["authorships"])

    def test_filters_by_search(self, db):
        pub = _create_pub(db)
        sd = _create_sd(db, pub)
        sp1 = _create_sp(db, source_id="sp-m", full_name="SpecialName")
        sp2 = _create_sp(db, source_id="sp-o", full_name="Autre")
        sa_match = _create_sa(
            db, sd, sp1, person_id=None, raw_author_name="SpecialName"
        )
        _create_sa(db, sd, sp2, person_id=None, raw_author_name="Autre")

        res = list_orphan_authorships(db, search="Special", page=1, per_page=50)
        ids = [a["authorship_id"] for a in res["authorships"]]
        assert sa_match in ids


class TestPersonExists:
    def test_true_when_exists(self, db):
        pid = _create_person(db)
        assert person_exists(db, pid) is True

    def test_false_when_missing(self, db):
        assert person_exists(db, 999_999) is False


class TestNameFormAuthorships:
    def test_returns_authorships_and_other_persons(self, db):
        pid = _create_person(db, last="Dupond")
        other = _create_person(db, last="Martin")
        pub = _create_pub(db)
        sd = _create_sd(db, pub)
        sp = _create_sp(db)
        _create_sa(db, sd, sp, person_id=pid, author_name_normalized="dupond j")
        # Forme partagée avec other
        db.execute(
            "INSERT INTO person_name_forms (name_form, person_ids) VALUES ('dupond j', %s)",
            ([pid, other],),
        )

        res = name_form_authorships(db, pid, "dupond j")
        assert len(res["authorships"]) >= 1
        other_ids = [p["id"] for p in res["other_persons"]]
        assert other in other_ids


class TestNameFormRemainingAuthorships:
    def test_counts_remaining(self, db):
        pid = _create_person(db)
        pub = _create_pub(db)
        sd = _create_sd(db, pub)
        sp = _create_sp(db)
        _create_sa(db, sd, sp, person_id=pid, author_name_normalized="x")
        assert name_form_remaining_authorships(db, pid, "x") == 1
        assert name_form_remaining_authorships(db, pid, "autre") == 0


class TestHalDuplicateAccounts:
    def test_detects_person_with_two_hal_accounts(self, db):
        pid = _create_person(db)
        _create_sp(db, source_id="hal-1", person_id=pid, hal_person_id=42, full_name="A")
        _create_sp(db, source_id="hal-2", person_id=pid, hal_person_id=43, full_name="B")

        res = hal_duplicate_accounts(db, page=1, per_page=50)
        assert res["total"] >= 1
        ours = next((p for p in res["persons"] if p["person_id"] == pid), None)
        assert ours is not None
        assert len(ours["hal_accounts"]) == 2

    def test_ignores_single_account(self, db):
        pid = _create_person(db)
        _create_sp(db, source_id="hal-1", person_id=pid, hal_person_id=42)
        res = hal_duplicate_accounts(db, page=1, per_page=50)
        assert not any(p["person_id"] == pid for p in res["persons"])
