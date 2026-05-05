"""Tests d'intégration pour `infrastructure.db.queries.persons.admin` (async)."""

import json

from infrastructure.db.queries.persons.admin import (
    hal_duplicate_accounts,
    list_orphan_authorships,
    name_form_authorships,
    name_form_remaining_authorships,
    orphan_authorships_count,
    person_exists,
)


async def _create_person(db, last="A", first="Z", rejected=False):
    await db.execute(
        "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized, rejected) "
        "VALUES (%s, %s, lower(%s), lower(%s), %s) RETURNING id",
        (last, first, last, first, rejected),
    )
    row = await db.fetchone()
    return row["id"]


async def _create_pub(db, doc_type="article"):
    await db.execute(
        "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
        "VALUES ('X', 'x', 2024, %s::doc_type) RETURNING id",
        (doc_type,),
    )
    row = await db.fetchone()
    return row["id"]


async def _create_sd(db, pub_id, source="hal", source_id="h1"):
    await db.execute(
        "INSERT INTO source_publications (source, source_id, title, publication_id) "
        "VALUES (%s, %s, 'X', %s) RETURNING id",
        (source, source_id, pub_id),
    )
    row = await db.fetchone()
    return row["id"]


async def _create_sp(
    db,
    source="hal",
    source_id="sp1",
    person_id=None,
    full_name="X",
    hal_person_id=None,
    idhal=None,
    orcid=None,
):
    source_ids = {}
    if hal_person_id is not None:
        source_ids["hal_person_id"] = hal_person_id
    if idhal:
        source_ids["idhal"] = idhal
    await db.execute(
        """
        INSERT INTO source_persons (source, source_id, full_name, person_id, source_ids, orcid)
        VALUES (%s, %s, %s, %s, %s::jsonb, %s) RETURNING id
        """,
        (
            source,
            source_id,
            full_name,
            person_id,
            json.dumps(source_ids) if source_ids else None,
            orcid,
        ),
    )
    row = await db.fetchone()
    return row["id"]


async def _create_sa(
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
    await db.execute(
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
    row = await db.fetchone()
    return row["id"]


class TestOrphanAuthorshipsCount:
    async def test_counts_orphans(self, async_db):
        pub = await _create_pub(async_db)
        sd = await _create_sd(async_db, pub)
        sp = await _create_sp(async_db)
        await _create_sa(async_db, sd, sp, person_id=None)  # orpheline
        sp2 = await _create_sp(async_db, source_id="sp2")
        pid = await _create_person(async_db)
        await _create_sa(async_db, sd, sp2, person_id=pid)  # attribuée

        count = await orphan_authorships_count(async_db)
        assert count["total"] >= 1

    async def test_excludes_non_uca(self, async_db):
        pub = await _create_pub(async_db)
        sd = await _create_sd(async_db, pub)
        sp = await _create_sp(async_db)
        await _create_sa(async_db, sd, sp, person_id=None, in_perimeter=False)
        count = await orphan_authorships_count(async_db)
        assert count["total"] == 0

    async def test_excludes_memoir(self, async_db):
        pub = await _create_pub(async_db, doc_type="memoir")
        sd = await _create_sd(async_db, pub)
        sp = await _create_sp(async_db)
        await _create_sa(async_db, sd, sp, person_id=None)
        count = await orphan_authorships_count(async_db)
        assert count["total"] == 0


class TestListOrphanAuthorships:
    async def test_lists_orphan_authorships(self, async_db):
        pub = await _create_pub(async_db)
        sd = await _create_sd(async_db, pub)
        sp = await _create_sp(async_db, full_name="Dupond Jean")
        sa = await _create_sa(async_db, sd, sp, person_id=None, raw_author_name="Dupond Jean")

        res = await list_orphan_authorships(async_db, search="", page=1, per_page=50)
        assert res["total"] >= 1
        assert any(a["authorship_id"] == sa for a in res["authorships"])

    async def test_filters_by_search(self, async_db):
        pub = await _create_pub(async_db)
        sd = await _create_sd(async_db, pub)
        sp1 = await _create_sp(async_db, source_id="sp-m", full_name="SpecialName")
        sp2 = await _create_sp(async_db, source_id="sp-o", full_name="Autre")
        sa_match = await _create_sa(
            async_db, sd, sp1, person_id=None, raw_author_name="SpecialName"
        )
        await _create_sa(async_db, sd, sp2, person_id=None, raw_author_name="Autre")

        res = await list_orphan_authorships(async_db, search="Special", page=1, per_page=50)
        ids = [a["authorship_id"] for a in res["authorships"]]
        assert sa_match in ids


class TestPersonExists:
    async def test_true_when_exists(self, async_db):
        pid = await _create_person(async_db)
        assert await person_exists(async_db, pid) is True

    async def test_false_when_missing(self, async_db):
        assert await person_exists(async_db, 999_999) is False


class TestNameFormAuthorships:
    async def test_returns_authorships_and_other_persons(self, async_db):
        pid = await _create_person(async_db, last="Dupond")
        other = await _create_person(async_db, last="Martin")
        pub = await _create_pub(async_db)
        sd = await _create_sd(async_db, pub)
        sp = await _create_sp(async_db)
        await _create_sa(async_db, sd, sp, person_id=pid, author_name_normalized="dupond j")
        await async_db.execute(
            "INSERT INTO person_name_forms (name_form, person_ids) VALUES ('dupond j', %s)",
            ([pid, other],),
        )

        res = await name_form_authorships(async_db, pid, "dupond j")
        assert len(res["authorships"]) >= 1
        other_ids = [p["id"] for p in res["other_persons"]]
        assert other in other_ids


class TestNameFormRemainingAuthorships:
    async def test_counts_remaining(self, async_db):
        pid = await _create_person(async_db)
        pub = await _create_pub(async_db)
        sd = await _create_sd(async_db, pub)
        sp = await _create_sp(async_db)
        await _create_sa(async_db, sd, sp, person_id=pid, author_name_normalized="x")
        assert await name_form_remaining_authorships(async_db, pid, "x") == 1
        assert await name_form_remaining_authorships(async_db, pid, "autre") == 0


class TestHalDuplicateAccounts:
    async def test_detects_person_with_two_hal_accounts(self, async_db):
        pid = await _create_person(async_db)
        await _create_sp(
            async_db, source_id="hal-1", person_id=pid, hal_person_id=42, full_name="A"
        )
        await _create_sp(
            async_db, source_id="hal-2", person_id=pid, hal_person_id=43, full_name="B"
        )

        res = await hal_duplicate_accounts(async_db, page=1, per_page=50)
        assert res["total"] >= 1
        ours = next((p for p in res["persons"] if p["person_id"] == pid), None)
        assert ours is not None
        assert len(ours["hal_accounts"]) == 2

    async def test_ignores_single_account(self, async_db):
        pid = await _create_person(async_db)
        await _create_sp(async_db, source_id="hal-1", person_id=pid, hal_person_id=42)
        res = await hal_duplicate_accounts(async_db, page=1, per_page=50)
        assert not any(p["person_id"] == pid for p in res["persons"])
