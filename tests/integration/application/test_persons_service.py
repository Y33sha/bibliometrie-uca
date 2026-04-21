"""Tests de caractérisation pour services/persons.py.

Couvre link/unlink_authorship (branches source invalide), add_identifier,
detach_name_form, assign_orphan_authorship (qui couvre _ensure_truth_authorship).
merge_person est déjà testé dans test_integration.py.
"""

import pytest

from application.persons import (
    add_identifier,
    add_identifiers_from_authorships,
    assign_orphan_authorship,
    async_create_person,
    batch_assign_orphan_authorships,
    detach_authorships,
    detach_name_form,
    link_authorship,
    mark_distinct,
    reassign_identifier,
    remove_identifier,
    set_rejected,
    unlink_authorship,
    update_identifier_status,
    update_name,
)
from domain.errors import NotFoundError, ValidationError
from infrastructure.repositories import (
    async_authorship_repository,
    async_person_repository,
    authorship_repository,
    person_repository,
)


@pytest.fixture
def authorship_repo(db):
    return authorship_repository(db)


@pytest.fixture
def repo(db):
    return person_repository(db)


@pytest.fixture
def async_authorship_repo(async_db):
    return async_authorship_repository(async_db)


@pytest.fixture
def async_repo(async_db):
    return async_person_repository(async_db)


# ── Helpers ────────────────────────────────────────────────────────


def _insert_person(db, last="Dupont", first="Jean"):
    db.execute(
        """
        INSERT INTO persons (last_name, first_name,
                             last_name_normalized, first_name_normalized)
        VALUES (%s, %s, lower(%s), lower(%s))
        RETURNING id
        """,
        (last, first, last, first),
    )
    return db.fetchone()["id"]


def _insert_publication(db, title="Test"):
    db.execute(
        "INSERT INTO publications (title, pub_year) VALUES (%s, 2024) RETURNING id",
        (title,),
    )
    return db.fetchone()["id"]


def _insert_source_publication(db, publication_id, source="hal", source_id="hal-1"):
    db.execute(
        """
        INSERT INTO source_publications (source, source_id, title, publication_id)
        VALUES (%s, %s, 'Test', %s)
        RETURNING id
        """,
        (source, source_id, publication_id),
    )
    return db.fetchone()["id"]


def _insert_source_person(
    db, source="hal", source_id="hal-p-1", full_name="Jean Dupont", source_ids=None
):
    import json

    db.execute(
        """
        INSERT INTO source_persons (source, source_id, full_name, source_ids)
        VALUES (%s, %s, %s, %s::jsonb)
        RETURNING id
        """,
        (source, source_id, full_name, json.dumps(source_ids) if source_ids else None),
    )
    return db.fetchone()["id"]


def _insert_source_authorship(
    db,
    source_publication_id,
    source_person_id,
    source="hal",
    person_id=None,
    author_name_normalized="jean dupont",
    excluded=False,
):
    db.execute(
        """
        INSERT INTO source_authorships (source, source_publication_id,
                                        source_person_id, person_id,
                                        author_name_normalized, excluded)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            source,
            source_publication_id,
            source_person_id,
            person_id,
            author_name_normalized,
            excluded,
        ),
    )
    return db.fetchone()["id"]


async def _a_insert_person(db, last="Dupont", first="Jean"):
    await db.execute(
        """
        INSERT INTO persons (last_name, first_name,
                             last_name_normalized, first_name_normalized)
        VALUES (%s, %s, lower(%s), lower(%s))
        RETURNING id
        """,
        (last, first, last, first),
    )
    return (await db.fetchone())["id"]


async def _a_insert_publication(db, title="Test"):
    await db.execute(
        "INSERT INTO publications (title, pub_year) VALUES (%s, 2024) RETURNING id",
        (title,),
    )
    return (await db.fetchone())["id"]


async def _a_insert_source_publication(db, publication_id, source="hal", source_id="hal-1"):
    await db.execute(
        """
        INSERT INTO source_publications (source, source_id, title, publication_id)
        VALUES (%s, %s, 'Test', %s)
        RETURNING id
        """,
        (source, source_id, publication_id),
    )
    return (await db.fetchone())["id"]


async def _a_insert_source_person(
    db, source="hal", source_id="hal-p-1", full_name="Jean Dupont", source_ids=None
):
    import json

    await db.execute(
        """
        INSERT INTO source_persons (source, source_id, full_name, source_ids)
        VALUES (%s, %s, %s, %s::jsonb)
        RETURNING id
        """,
        (source, source_id, full_name, json.dumps(source_ids) if source_ids else None),
    )
    return (await db.fetchone())["id"]


async def _a_insert_source_authorship(
    db,
    source_publication_id,
    source_person_id,
    source="hal",
    person_id=None,
    author_name_normalized="jean dupont",
    excluded=False,
):
    await db.execute(
        """
        INSERT INTO source_authorships (source, source_publication_id,
                                        source_person_id, person_id,
                                        author_name_normalized, excluded)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            source,
            source_publication_id,
            source_person_id,
            person_id,
            author_name_normalized,
            excluded,
        ),
    )
    return (await db.fetchone())["id"]


# ── link_authorship / unlink_authorship ────────────────────────────


class TestLinkAuthorship:
    def test_ignores_invalid_source(self, db, repo):
        """Source inconnue → no-op silencieux (pas d'exception)."""
        link_authorship(db, 1, "invalid", 1, repo=repo)

    def test_sets_person_id_on_source_authorship(self, db, repo):
        person_id = _insert_person(db)
        pub_id = _insert_publication(db)
        sp_id = _insert_source_publication(db, pub_id)
        sp_person = _insert_source_person(db)
        sa_id = _insert_source_authorship(db, sp_id, sp_person)

        link_authorship(db, person_id, "hal", sa_id, repo=repo)

        db.execute("SELECT person_id FROM source_authorships WHERE id = %s", (sa_id,))
        assert db.fetchone()["person_id"] == person_id

    def test_dual_write_hal_person(self, db, repo):
        """Pour HAL avec hal_person_id, propage aussi à source_persons."""
        person_id = _insert_person(db)
        pub_id = _insert_publication(db)
        sp_id = _insert_source_publication(db, pub_id)
        sp_person = _insert_source_person(db, source_ids={"hal_person_id": 42})
        sa_id = _insert_source_authorship(db, sp_id, sp_person)

        link_authorship(
            db,
            person_id,
            "hal",
            sa_id,
            source_person_id=sp_person,
            has_hal_person_id=True,
            repo=repo,
        )

        db.execute("SELECT person_id FROM source_persons WHERE id = %s", (sp_person,))
        assert db.fetchone()["person_id"] == person_id


class TestUnlinkAuthorship:
    def test_ignores_invalid_source(self, db, repo):
        unlink_authorship(db, 1, "invalid", 1, repo=repo)  # no-op silencieux

    def test_unsets_person_id(self, db, repo):
        person_id = _insert_person(db)
        pub_id = _insert_publication(db)
        sp_id = _insert_source_publication(db, pub_id)
        sp_person = _insert_source_person(db)
        sa_id = _insert_source_authorship(db, sp_id, sp_person, person_id=person_id)

        unlink_authorship(db, person_id, "hal", sa_id, repo=repo)

        db.execute("SELECT person_id FROM source_authorships WHERE id = %s", (sa_id,))
        assert db.fetchone()["person_id"] is None

    def test_noop_if_person_id_mismatch(self, db, repo):
        """Ne détache pas si l'authorship est liée à une autre personne."""
        p1 = _insert_person(db, "Dupont", "Jean")
        p2 = _insert_person(db, "Martin", "Sophie")
        pub_id = _insert_publication(db)
        sp_id = _insert_source_publication(db, pub_id)
        sp_person = _insert_source_person(db)
        sa_id = _insert_source_authorship(db, sp_id, sp_person, person_id=p1)

        unlink_authorship(db, p2, "hal", sa_id, repo=repo)

        db.execute("SELECT person_id FROM source_authorships WHERE id = %s", (sa_id,))
        assert db.fetchone()["person_id"] == p1  # intact


# ── add_identifier ─────────────────────────────────────────────────


class TestAddIdentifier:
    def test_inserts_new(self, db, repo):
        person_id = _insert_person(db)
        add_identifier(db, person_id, "orcid", "0000-0001-2345-6789", repo=repo)
        db.execute(
            "SELECT status FROM person_identifiers WHERE id_type='orcid' AND id_value=%s",
            ("0000-0001-2345-6789",),
        )
        assert db.fetchone()["status"] == "pending"

    def test_reassigns_if_rejected(self, db, repo):
        p1 = _insert_person(db, "A", "A")
        p2 = _insert_person(db, "B", "B")
        add_identifier(db, p1, "orcid", "0000-0001", repo=repo)
        db.execute("UPDATE person_identifiers SET status='rejected' WHERE id_value='0000-0001'")
        add_identifier(db, p2, "orcid", "0000-0001", repo=repo)

        db.execute("SELECT person_id, status FROM person_identifiers WHERE id_value='0000-0001'")
        row = db.fetchone()
        assert row["person_id"] == p2
        assert row["status"] == "pending"

    def test_does_not_override_pending(self, db, repo):
        """Si le même identifiant existe en 'pending', on ne touche pas."""
        p1 = _insert_person(db, "A", "A")
        p2 = _insert_person(db, "B", "B")
        add_identifier(db, p1, "orcid", "0000-0001", repo=repo)
        add_identifier(db, p2, "orcid", "0000-0001", repo=repo)  # devrait rien faire

        db.execute("SELECT person_id FROM person_identifiers WHERE id_value='0000-0001'")
        assert db.fetchone()["person_id"] == p1

    def test_idhal_attaches_hal_source_person(self, db, repo):
        """Ajouter un idhal à une personne rattache le compte HAL correspondant."""
        person_id = _insert_person(db)
        sp = _insert_source_person(db, source_ids={"idhal": "jean-dupont"})

        add_identifier(db, person_id, "idhal", "jean-dupont", repo=repo)

        db.execute("SELECT person_id FROM source_persons WHERE id = %s", (sp,))
        assert db.fetchone()["person_id"] == person_id


class TestRemoveIdentifier:
    async def test_removes_existing(self, async_db, async_repo):
        p = await _a_insert_person(async_db)
        await async_db.execute(
            "INSERT INTO person_identifiers (person_id, id_type, id_value, source, status) "
            "VALUES (%s, 'orcid', '0000-0001', 'auto', 'pending')",
            (p,),
        )
        await remove_identifier(async_db, p, "orcid", "0000-0001", repo=async_repo)
        await async_db.execute("SELECT id FROM person_identifiers WHERE id_value = '0000-0001'")
        assert await async_db.fetchone() is None

    async def test_raises_not_found(self, async_db, async_repo):
        p = await _a_insert_person(async_db)
        with pytest.raises(NotFoundError):
            await remove_identifier(async_db, p, "orcid", "unknown", repo=async_repo)


class TestUpdateIdentifierStatus:
    async def test_sets_status(self, async_db, async_repo):
        p = await _a_insert_person(async_db)
        await async_db.execute(
            "INSERT INTO person_identifiers (person_id, id_type, id_value, source, status) "
            "VALUES (%s, 'orcid', '0000-0001', 'auto', 'pending') RETURNING id",
            (p,),
        )
        ident_id = (await async_db.fetchone())["id"]

        row = await update_identifier_status(async_db, ident_id, "confirmed", repo=async_repo)

        assert row["status"] == "confirmed"

    async def test_raises_not_found(self, async_db, async_repo):
        with pytest.raises(NotFoundError):
            await update_identifier_status(async_db, 999999, "confirmed", repo=async_repo)


class TestReassignIdentifier:
    async def test_reassigns(self, async_db, async_repo):
        p1 = await _a_insert_person(async_db, "A", "A")
        p2 = await _a_insert_person(async_db, "B", "B")
        await async_db.execute(
            "INSERT INTO person_identifiers (person_id, id_type, id_value, source, status) "
            "VALUES (%s, 'orcid', '0000-0001', 'auto', 'pending') RETURNING id",
            (p1,),
        )
        ident_id = (await async_db.fetchone())["id"]

        await reassign_identifier(async_db, ident_id, p2, repo=async_repo)

        await async_db.execute(
            "SELECT person_id, status::text AS status FROM person_identifiers WHERE id = %s",
            (ident_id,),
        )
        row = await async_db.fetchone()
        assert row["person_id"] == p2
        assert row["status"] == "pending"

    async def test_raises_not_found(self, async_db, async_repo):
        p = await _a_insert_person(async_db)
        with pytest.raises(NotFoundError):
            await reassign_identifier(async_db, 999999, p, repo=async_repo)


class TestSetRejected:
    async def test_marks_rejected(self, async_db, async_repo):
        p = await _a_insert_person(async_db)
        await set_rejected(async_db, p, True, repo=async_repo)
        await async_db.execute("SELECT rejected FROM persons WHERE id = %s", (p,))
        assert (await async_db.fetchone())["rejected"] is True

    async def test_unmarks(self, async_db, async_repo):
        p = await _a_insert_person(async_db)
        await set_rejected(async_db, p, True, repo=async_repo)
        await set_rejected(async_db, p, False, repo=async_repo)
        await async_db.execute("SELECT rejected FROM persons WHERE id = %s", (p,))
        assert (await async_db.fetchone())["rejected"] is False

    async def test_raises_not_found(self, async_db, async_repo):
        with pytest.raises(NotFoundError):
            await set_rejected(async_db, 999999, True, repo=async_repo)


class TestUpdateName:
    async def test_updates_name_and_refreshes_forms(self, async_db, async_repo):
        p = await _a_insert_person(async_db, "Dupont", "Jean")
        # La forme 'dupont jean' doit exister pour vérifier le refresh
        await async_db.execute(
            "INSERT INTO person_name_forms (name_form, person_ids, sources) "
            "VALUES ('dupont jean', ARRAY[%s]::integer[], ARRAY['persons']::text[])",
            (p,),
        )
        await async_db.execute("SELECT id FROM person_name_forms WHERE name_form = 'dupont jean'")
        assert await async_db.fetchone() is not None

        await update_name(async_db, p, "Martin", "Sophie", repo=async_repo)

        await async_db.execute("SELECT last_name, first_name FROM persons WHERE id = %s", (p,))
        row = await async_db.fetchone()
        assert row["last_name"] == "Martin"
        assert row["first_name"] == "Sophie"

        # Nouvelle forme créée
        await async_db.execute("SELECT id FROM person_name_forms WHERE name_form = 'martin sophie'")
        assert await async_db.fetchone() is not None

    async def test_raises_not_found(self, async_db, async_repo):
        with pytest.raises(NotFoundError):
            await update_name(async_db, 999999, "X", "X", repo=async_repo)


# ── batch_assign_orphan_authorships ─────────────────────────────────


class TestBatchAssignOrphanAuthorships:
    async def _setup_uca(self, db):
        import json

        await db.execute(
            """
            INSERT INTO structures (code, name, structure_type)
            VALUES ('UCA', 'UCA', 'universite'::structure_type)
            RETURNING id
            """
        )
        uca = (await db.fetchone())["id"]
        await db.execute(
            "INSERT INTO perimeters (code, name, structure_ids) VALUES ('uca', 'UCA', %s)",
            ([uca],),
        )
        await db.execute(
            "INSERT INTO config (key, value) VALUES ('perimeter_persons', %s::jsonb)",
            (json.dumps("uca"),),
        )

    async def test_empty_list_returns_zero(self, async_db, async_repo):
        await self._setup_uca(async_db)
        person_id = await _a_insert_person(async_db)
        assert await batch_assign_orphan_authorships(async_db, person_id, [], repo=async_repo) == 0

    async def test_assigns_and_creates_truth(self, async_db, async_repo):
        await self._setup_uca(async_db)
        person_id = await _a_insert_person(async_db)
        pub_id = await _a_insert_publication(async_db)
        sp_hal = await _a_insert_source_publication(async_db, pub_id, source="hal", source_id="h-1")
        sp_oa = await _a_insert_source_publication(
            async_db, pub_id, source="openalex", source_id="W1"
        )
        sp_person_hal = await _a_insert_source_person(async_db, source="hal", source_id="hal-p-1")
        sp_person_oa = await _a_insert_source_person(
            async_db, source="openalex", source_id="oa-p-1"
        )
        sa1 = await _a_insert_source_authorship(
            async_db, sp_hal, sp_person_hal, source="hal", author_name_normalized="jean dupont"
        )
        sa2 = await _a_insert_source_authorship(
            async_db, sp_oa, sp_person_oa, source="openalex", author_name_normalized="jean dupont"
        )

        assigned = await batch_assign_orphan_authorships(
            async_db, person_id, [sa1, sa2], repo=async_repo
        )

        assert assigned == 2
        # authorship vérité créée pour la publication
        await async_db.execute(
            "SELECT id FROM authorships WHERE publication_id = %s AND person_id = %s",
            (pub_id, person_id),
        )
        assert await async_db.fetchone() is not None
        # FK posée sur les 2 source_authorships
        await async_db.execute(
            "SELECT authorship_id FROM source_authorships WHERE id = ANY(%s)",
            ([sa1, sa2],),
        )
        rows = await async_db.fetchall()
        assert all(r["authorship_id"] is not None for r in rows)

    async def test_skips_already_assigned(self, async_db, async_repo):
        await self._setup_uca(async_db)
        p1 = await _a_insert_person(async_db, "A", "A")
        p2 = await _a_insert_person(async_db, "B", "B")
        pub_id = await _a_insert_publication(async_db)
        sp_id = await _a_insert_source_publication(async_db, pub_id)
        sp_person = await _a_insert_source_person(async_db)
        # sa1 déjà assignée à p1
        sa1 = await _a_insert_source_authorship(async_db, sp_id, sp_person, person_id=p1)

        assigned = await batch_assign_orphan_authorships(async_db, p2, [sa1], repo=async_repo)

        assert assigned == 0  # pas d'orpheline à rattacher
        await async_db.execute("SELECT person_id FROM source_authorships WHERE id = %s", (sa1,))
        assert (await async_db.fetchone())["person_id"] == p1  # inchangé


# ── detach_authorships ─────────────────────────────────────────────


class TestDetachAuthorships:
    async def test_detaches_and_removes_truth_if_orphan(
        self, async_db, async_repo, async_authorship_repo
    ):
        person_id = await _a_insert_person(async_db)
        pub_id = await _a_insert_publication(async_db)
        sp_id = await _a_insert_source_publication(async_db, pub_id)
        sp_person = await _a_insert_source_person(async_db)
        await async_db.execute(
            "INSERT INTO authorships (publication_id, person_id) VALUES (%s, %s) RETURNING id",
            (pub_id, person_id),
        )
        auth_id = (await async_db.fetchone())["id"]
        sa_id = await _a_insert_source_authorship(async_db, sp_id, sp_person, person_id=person_id)

        result = await detach_authorships(
            async_db,
            person_id,
            authorships=[{"source": "hal", "authorship_id": sa_id}],
            repo=async_repo,
            authorship_repo=async_authorship_repo,
        )

        assert result["detached"] == 1
        assert result["deleted_authorships"] == 1
        # source_authorship détaché
        await async_db.execute("SELECT person_id FROM source_authorships WHERE id = %s", (sa_id,))
        assert (await async_db.fetchone())["person_id"] is None
        # authorship vérité supprimée (orpheline)
        await async_db.execute("SELECT id FROM authorships WHERE id = %s", (auth_id,))
        assert await async_db.fetchone() is None

    async def test_cleans_name_form_when_no_remaining(
        self, async_db, async_repo, async_authorship_repo
    ):
        person_id = await async_create_person(async_db, "Dupont", "Jean", repo=async_repo)
        # add_name_form simulé via async_create_person

        # Pas de source_authorship portant "dupont jean" → la forme est nettoyée
        result = await detach_authorships(
            async_db,
            person_id,
            authorships=[],
            name_form="dupont jean",
            repo=async_repo,
            authorship_repo=async_authorship_repo,
        )
        assert result["cleaned_form"] is True

        await async_db.execute("SELECT id FROM person_name_forms WHERE name_form = 'dupont jean'")
        # La forme a été retirée ou la person_id a été enlevée
        row = await async_db.fetchone()
        if row:
            await async_db.execute(
                "SELECT person_ids FROM person_name_forms WHERE name_form = 'dupont jean'"
            )
            assert person_id not in ((await async_db.fetchone())["person_ids"] or [])

    async def test_keeps_name_form_if_another_authorship_uses_it(
        self, async_db, async_repo, async_authorship_repo
    ):
        person_id = await async_create_person(async_db, "Dupont", "Jean", repo=async_repo)
        pub_id = await _a_insert_publication(async_db)
        sp_id = await _a_insert_source_publication(async_db, pub_id)
        sp_person = await _a_insert_source_person(async_db)
        # source_authorship portant la forme "dupont jean"
        await _a_insert_source_authorship(
            async_db,
            sp_id,
            sp_person,
            person_id=person_id,
            author_name_normalized="dupont jean",
        )

        result = await detach_authorships(
            async_db,
            person_id,
            authorships=[],
            name_form="dupont jean",
            repo=async_repo,
            authorship_repo=async_authorship_repo,
        )

        assert result["cleaned_form"] is False


class TestMarkDistinctPersons:
    async def test_inserts_ordered_pair(self, async_db, async_repo):
        p1 = await _a_insert_person(async_db, "A", "A")
        p2 = await _a_insert_person(async_db, "B", "B")
        await mark_distinct(async_db, p2, p1, repo=async_repo)  # ordre inverse
        await async_db.execute(
            "SELECT COUNT(*) AS n FROM distinct_persons "
            "WHERE person_id_a = %s AND person_id_b = %s",
            (min(p1, p2), max(p1, p2)),
        )
        assert (await async_db.fetchone())["n"] == 1

    async def test_idempotent(self, async_db, async_repo):
        p1 = await _a_insert_person(async_db, "A", "A")
        p2 = await _a_insert_person(async_db, "B", "B")
        await mark_distinct(async_db, p1, p2, repo=async_repo)
        await mark_distinct(async_db, p1, p2, repo=async_repo)  # ON CONFLICT DO NOTHING
        await async_db.execute(
            "SELECT COUNT(*) AS n FROM distinct_persons "
            "WHERE person_id_a = %s AND person_id_b = %s",
            (min(p1, p2), max(p1, p2)),
        )
        assert (await async_db.fetchone())["n"] == 1


class TestAddIdentifiersFromAuthorships:
    def test_adds_orcid_idhal_idref_once(self, db, repo):
        person_id = _insert_person(db)
        authorships = [
            {"source": "hal", "orcid": "0000-0001", "idhal": "jdupont"},
            {"source": "scanr", "orcid": "0000-0001", "idref": "123456"},  # orcid dédupliqué
        ]
        add_identifiers_from_authorships(db, person_id, authorships, repo=repo)

        db.execute(
            """SELECT id_type, id_value, source FROM person_identifiers
               WHERE person_id = %s ORDER BY id_type""",
            (person_id,),
        )
        rows = db.fetchall()
        id_types = [r["id_type"] for r in rows]
        assert id_types == ["idhal", "idref", "orcid"]


# ── detach_name_form ───────────────────────────────────────────────


class TestDetachNameForm:
    async def test_removes_person_from_form(self, async_db, async_repo):
        p1 = await async_create_person(async_db, "Dupont", "Jean", repo=async_repo)
        p2 = await async_create_person(
            async_db, "Dupont", "Jean", repo=async_repo
        )  # même forme 'dupont jean'

        await detach_name_form(async_db, p1, "dupont jean", repo=async_repo)

        await async_db.execute(
            "SELECT person_ids FROM person_name_forms WHERE name_form = 'dupont jean'"
        )
        row = await async_db.fetchone()
        assert row is not None
        assert p1 not in row["person_ids"]
        assert p2 in row["person_ids"]

    async def test_deletes_form_when_last_person_detached(self, async_db, async_repo):
        person_id = await async_create_person(async_db, "Unique", "Name", repo=async_repo)

        await detach_name_form(async_db, person_id, "name unique", repo=async_repo)

        await async_db.execute("SELECT id FROM person_name_forms WHERE name_form = 'name unique'")
        assert await async_db.fetchone() is None


# ── assign_orphan_authorship (+ _ensure_truth_authorship) ──────────


class TestAssignOrphanAuthorship:
    async def _setup(self, db):
        """Monte un périmètre UCA minimal (nécessaire pour _ensure_truth_authorship)."""
        import json

        await db.execute(
            """
            INSERT INTO structures (code, name, structure_type)
            VALUES ('UCA', 'UCA', 'universite'::structure_type)
            RETURNING id
            """
        )
        uca_id = (await db.fetchone())["id"]
        await db.execute(
            "INSERT INTO perimeters (code, name, structure_ids) VALUES ('uca', 'UCA', %s)",
            ([uca_id],),
        )
        await db.execute(
            "INSERT INTO config (key, value) VALUES ('perimeter_persons', %s::jsonb)",
            (json.dumps("uca"),),
        )
        return uca_id

    async def test_raises_on_invalid_source(self, async_db, async_repo):
        with pytest.raises(ValidationError, match="Source inconnue"):
            await assign_orphan_authorship(async_db, 1, "invalid", 1, repo=async_repo)

    async def test_returns_false_if_already_assigned(self, async_db, async_repo):
        """Si l'authorship a déjà un person_id, l'UPDATE ne matche pas."""
        await self._setup(async_db)
        person_id = await _a_insert_person(async_db)
        other_id = await _a_insert_person(async_db, "Other", "Author")
        pub_id = await _a_insert_publication(async_db)
        sp_id = await _a_insert_source_publication(async_db, pub_id)
        sp_person = await _a_insert_source_person(async_db)
        sa_id = await _a_insert_source_authorship(async_db, sp_id, sp_person, person_id=other_id)

        assert (
            await assign_orphan_authorship(async_db, person_id, "hal", sa_id, repo=async_repo)
            is False
        )

    async def test_assigns_and_creates_truth_authorship(self, async_db, async_repo):
        await self._setup(async_db)
        person_id = await _a_insert_person(async_db)
        pub_id = await _a_insert_publication(async_db)
        sp_id = await _a_insert_source_publication(async_db, pub_id)
        sp_person = await _a_insert_source_person(async_db)
        sa_id = await _a_insert_source_authorship(async_db, sp_id, sp_person)  # orpheline

        result = await assign_orphan_authorship(async_db, person_id, "hal", sa_id, repo=async_repo)

        assert result is True
        # person_id assigné sur source_authorship
        await async_db.execute(
            "SELECT person_id, authorship_id FROM source_authorships WHERE id = %s", (sa_id,)
        )
        row = await async_db.fetchone()
        assert row["person_id"] == person_id
        assert row["authorship_id"] is not None

        # authorship vérité créée
        await async_db.execute(
            "SELECT id FROM authorships WHERE publication_id = %s AND person_id = %s",
            (pub_id, person_id),
        )
        assert await async_db.fetchone() is not None

    async def test_skips_name_form_if_excluded(self, async_db, async_repo):
        """Si la source authorship est excluded, pas d'ajout de name_form."""
        await self._setup(async_db)
        person_id = await _a_insert_person(async_db, "Zzz", "Zzz")  # forme 'zzz' / 'zzz zzz'
        pub_id = await _a_insert_publication(async_db)
        sp_id = await _a_insert_source_publication(async_db, pub_id)
        sp_person = await _a_insert_source_person(async_db)
        sa_id = await _a_insert_source_authorship(
            async_db,
            sp_id,
            sp_person,
            author_name_normalized="other name",
            excluded=True,
        )

        await assign_orphan_authorship(async_db, person_id, "hal", sa_id, repo=async_repo)

        # Aucune nouvelle name_form 'other name' n'a été créée
        await async_db.execute("SELECT id FROM person_name_forms WHERE name_form = 'other name'")
        assert await async_db.fetchone() is None
