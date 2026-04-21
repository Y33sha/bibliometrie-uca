"""Tests de caractérisation pour services/authorships.py.

Documentent le comportement actuel des fonctions du service pour protéger
contre les régressions lors de refactos ultérieurs.
"""

import json

import pytest

from application.authorships import (
    delete_orphan_authorships,
    detach_source,
    exclude_authorship,
    move_authorships_for_source,
    propagate_uca_for_addresses,
    set_source_authorship_excluded,
    sync_person_id_from_source,
)
from domain.errors import NotFoundError, ValidationError
from infrastructure.db.queries.perimeter import PgAsyncPerimeterQueries, PgPerimeterQueries
from infrastructure.repositories import async_authorship_repository, authorship_repository


@pytest.fixture
def perimeter_queries():
    return PgPerimeterQueries()


@pytest.fixture
def async_perimeter_queries():
    return PgAsyncPerimeterQueries()


@pytest.fixture
def repo(db):
    return authorship_repository(db)


@pytest.fixture
def async_repo(async_db):
    return async_authorship_repository(async_db)


# ── Helpers ────────────────────────────────────────────────────────


def _create_person(db, last="Dupont", first="Jean"):
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


def _create_publication(db, title="Test Article", pub_year=2024):
    db.execute(
        "INSERT INTO publications (title, pub_year) VALUES (%s, %s) RETURNING id",
        (title, pub_year),
    )
    return db.fetchone()["id"]


def _create_source_publication(db, publication_id, source="hal", source_id="hal-1", title="Test"):
    db.execute(
        """
        INSERT INTO source_publications (source, source_id, title, publication_id)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (source, source_id, title, publication_id),
    )
    return db.fetchone()["id"]


def _create_source_person(db, source="hal", source_id="hal-p-1", full_name="Jean Dupont"):
    db.execute(
        """
        INSERT INTO source_persons (source, source_id, full_name)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (source, source_id, full_name),
    )
    return db.fetchone()["id"]


def _create_authorship(db, publication_id, person_id=None):
    db.execute(
        "INSERT INTO authorships (publication_id, person_id) VALUES (%s, %s) RETURNING id",
        (publication_id, person_id),
    )
    return db.fetchone()["id"]


def _create_source_authorship(
    db,
    source_publication_id,
    source_person_id,
    source="hal",
    person_id=None,
    authorship_id=None,
    excluded=False,
    in_perimeter=False,
    structure_ids=None,
):
    db.execute(
        """
        INSERT INTO source_authorships (source, source_publication_id,
                                        source_person_id, person_id,
                                        authorship_id, excluded,
                                        in_perimeter, structure_ids)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            source,
            source_publication_id,
            source_person_id,
            person_id,
            authorship_id,
            excluded,
            in_perimeter,
            structure_ids,
        ),
    )
    return db.fetchone()["id"]


def _create_structure(db, code="UCA", name="UCA", structure_type="universite"):
    db.execute(
        """
        INSERT INTO structures (code, name, structure_type)
        VALUES (%s, %s, %s::structure_type)
        RETURNING id
        """,
        (code, name, structure_type),
    )
    return db.fetchone()["id"]


def _create_perimeter(db, code, name, structure_ids):
    db.execute(
        """
        INSERT INTO perimeters (code, name, structure_ids)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (code, name, structure_ids),
    )
    return db.fetchone()["id"]


def _set_config(db, key, value):
    db.execute(
        "INSERT INTO config (key, value) VALUES (%s, %s::jsonb)",
        (key, json.dumps(value)),
    )


def _create_address(db, raw_text="Université Clermont Auvergne"):
    db.execute(
        """
        INSERT INTO addresses (raw_text, normalized_text)
        VALUES (%s, lower(%s))
        RETURNING id
        """,
        (raw_text, raw_text),
    )
    return db.fetchone()["id"]


def _link_address_structure(db, address_id, structure_id, is_confirmed=True):
    db.execute(
        """
        INSERT INTO address_structures (address_id, structure_id, is_confirmed)
        VALUES (%s, %s, %s)
        """,
        (address_id, structure_id, is_confirmed),
    )


def _link_sa_address(db, source_authorship_id, address_id):
    db.execute(
        """
        INSERT INTO source_authorship_addresses (source_authorship_id, address_id)
        VALUES (%s, %s)
        """,
        (source_authorship_id, address_id),
    )


# ── Helpers async ──────────────────────────────────────────────────


async def _a_create_person(db, last="Dupont", first="Jean"):
    await db.execute(
        """
        INSERT INTO persons (last_name, first_name,
                             last_name_normalized, first_name_normalized)
        VALUES (%s, %s, lower(%s), lower(%s))
        RETURNING id
        """,
        (last, first, last, first),
    )
    row = await db.fetchone()
    return row["id"]


async def _a_create_publication(db, title="Test Article", pub_year=2024):
    await db.execute(
        "INSERT INTO publications (title, pub_year) VALUES (%s, %s) RETURNING id",
        (title, pub_year),
    )
    row = await db.fetchone()
    return row["id"]


async def _a_create_source_publication(
    db, publication_id, source="hal", source_id="hal-1", title="Test"
):
    await db.execute(
        """
        INSERT INTO source_publications (source, source_id, title, publication_id)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (source, source_id, title, publication_id),
    )
    row = await db.fetchone()
    return row["id"]


async def _a_create_source_person(db, source="hal", source_id="hal-p-1", full_name="Jean Dupont"):
    await db.execute(
        """
        INSERT INTO source_persons (source, source_id, full_name)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (source, source_id, full_name),
    )
    row = await db.fetchone()
    return row["id"]


async def _a_create_authorship(db, publication_id, person_id=None):
    await db.execute(
        "INSERT INTO authorships (publication_id, person_id) VALUES (%s, %s) RETURNING id",
        (publication_id, person_id),
    )
    row = await db.fetchone()
    return row["id"]


async def _a_create_source_authorship(
    db,
    source_publication_id,
    source_person_id,
    source="hal",
    person_id=None,
    authorship_id=None,
    excluded=False,
    in_perimeter=False,
    structure_ids=None,
):
    await db.execute(
        """
        INSERT INTO source_authorships (source, source_publication_id,
                                        source_person_id, person_id,
                                        authorship_id, excluded,
                                        in_perimeter, structure_ids)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            source,
            source_publication_id,
            source_person_id,
            person_id,
            authorship_id,
            excluded,
            in_perimeter,
            structure_ids,
        ),
    )
    row = await db.fetchone()
    return row["id"]


async def _a_create_structure(db, code="UCA", name="UCA", structure_type="universite"):
    await db.execute(
        """
        INSERT INTO structures (code, name, structure_type)
        VALUES (%s, %s, %s::structure_type)
        RETURNING id
        """,
        (code, name, structure_type),
    )
    row = await db.fetchone()
    return row["id"]


async def _a_create_perimeter(db, code, name, structure_ids):
    await db.execute(
        """
        INSERT INTO perimeters (code, name, structure_ids)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (code, name, structure_ids),
    )
    row = await db.fetchone()
    return row["id"]


async def _a_set_config(db, key, value):
    await db.execute(
        "INSERT INTO config (key, value) VALUES (%s, %s::jsonb)",
        (key, json.dumps(value)),
    )


async def _a_create_address(db, raw_text="Université Clermont Auvergne"):
    await db.execute(
        """
        INSERT INTO addresses (raw_text, normalized_text)
        VALUES (%s, lower(%s))
        RETURNING id
        """,
        (raw_text, raw_text),
    )
    row = await db.fetchone()
    return row["id"]


async def _a_link_address_structure(db, address_id, structure_id, is_confirmed=True):
    await db.execute(
        """
        INSERT INTO address_structures (address_id, structure_id, is_confirmed)
        VALUES (%s, %s, %s)
        """,
        (address_id, structure_id, is_confirmed),
    )


async def _a_link_sa_address(db, source_authorship_id, address_id):
    await db.execute(
        """
        INSERT INTO source_authorship_addresses (source_authorship_id, address_id)
        VALUES (%s, %s)
        """,
        (source_authorship_id, address_id),
    )


# ── exclude_authorship ─────────────────────────────────────────────


class TestExcludeAuthorship:
    """exclude_authorship marque l'authorship vérité comme excluded et
    détache les source_authorships qui y référaient."""

    async def test_marks_excluded_and_detaches_sources(self, async_db, async_repo):
        person_id = await _a_create_person(async_db)
        pub_id = await _a_create_publication(async_db)
        sp_id = await _a_create_source_publication(async_db, pub_id)
        src_person_id = await _a_create_source_person(async_db)
        authorship_id = await _a_create_authorship(async_db, pub_id, person_id)
        sa_id = await _a_create_source_authorship(
            async_db, sp_id, src_person_id, person_id=person_id, authorship_id=authorship_id
        )

        result = await exclude_authorship(async_db, authorship_id, repo=async_repo)

        assert result is not None
        assert result["excluded"] is True

        # Source détachée : person_id et authorship_id remis à NULL
        await async_db.execute(
            "SELECT person_id, authorship_id FROM source_authorships WHERE id = %s",
            (sa_id,),
        )
        row = await async_db.fetchone()
        assert row["person_id"] is None
        assert row["authorship_id"] is None

    async def test_raises_not_found(self, async_db, async_repo):
        with pytest.raises(NotFoundError):
            await exclude_authorship(async_db, 999999, repo=async_repo)

    async def test_does_not_detach_unrelated_sources(self, async_db, async_repo):
        """Les sources d'autres personnes sur la même pub ne sont pas touchées."""
        pub_id = await _a_create_publication(async_db)
        sp_id = await _a_create_source_publication(async_db, pub_id)

        p1 = await _a_create_person(async_db, "Dupont", "Jean")
        p2 = await _a_create_person(async_db, "Martin", "Sophie")
        sp1 = await _a_create_source_person(async_db, source_id="hal-p-1")
        sp2 = await _a_create_source_person(async_db, source_id="hal-p-2")
        a1 = await _a_create_authorship(async_db, pub_id, p1)
        a2 = await _a_create_authorship(async_db, pub_id, p2)
        sa1 = await _a_create_source_authorship(
            async_db, sp_id, sp1, person_id=p1, authorship_id=a1
        )
        sa2 = await _a_create_source_authorship(
            async_db, sp_id, sp2, person_id=p2, authorship_id=a2
        )

        await exclude_authorship(async_db, a1, repo=async_repo)

        # sa1 détachée
        await async_db.execute("SELECT person_id FROM source_authorships WHERE id = %s", (sa1,))
        assert (await async_db.fetchone())["person_id"] is None
        # sa2 intacte
        await async_db.execute("SELECT person_id FROM source_authorships WHERE id = %s", (sa2,))
        assert (await async_db.fetchone())["person_id"] == p2


# ── detach_source ──────────────────────────────────────────────────


class TestDetachSource:
    """detach_source retire le lien FK d'une source_authorship vers l'authorship
    vérité. Supprime l'authorship vérité si plus aucune source ne l'atteste."""

    async def test_raises_on_invalid_source(self, async_db, async_repo):
        with pytest.raises(ValidationError, match="Source inconnue"):
            await detach_source(async_db, 1, "invalid_source", repo=async_repo)

    async def test_returns_false_if_no_authorship_linked(self, async_db, async_repo):
        pub_id = await _a_create_publication(async_db)
        sp_id = await _a_create_source_publication(async_db, pub_id)
        src_person_id = await _a_create_source_person(async_db)
        # source_authorship sans authorship_id
        sa_id = await _a_create_source_authorship(async_db, sp_id, src_person_id)

        assert await detach_source(async_db, sa_id, "hal", repo=async_repo) is False

    async def test_deletes_authorship_when_last_source_removed(self, async_db, async_repo):
        """Une seule source atteste l'authorship → le détacher supprime l'authorship."""
        person_id = await _a_create_person(async_db)
        pub_id = await _a_create_publication(async_db)
        sp_id = await _a_create_source_publication(async_db, pub_id)
        src_person_id = await _a_create_source_person(async_db)
        authorship_id = await _a_create_authorship(async_db, pub_id, person_id)
        sa_id = await _a_create_source_authorship(
            async_db, sp_id, src_person_id, person_id=person_id, authorship_id=authorship_id
        )

        assert await detach_source(async_db, sa_id, "hal", repo=async_repo) is True

        await async_db.execute("SELECT id FROM authorships WHERE id = %s", (authorship_id,))
        assert await async_db.fetchone() is None

    async def test_keeps_authorship_when_other_sources_remain(self, async_db, async_repo):
        """Deux sources attestent l'authorship → détacher une garde l'authorship."""
        person_id = await _a_create_person(async_db)
        pub_id = await _a_create_publication(async_db)
        sp_hal = await _a_create_source_publication(
            async_db, pub_id, source="hal", source_id="hal-1"
        )
        sp_oa = await _a_create_source_publication(
            async_db, pub_id, source="openalex", source_id="W1"
        )
        p_hal = await _a_create_source_person(async_db, source="hal", source_id="hal-p-1")
        p_oa = await _a_create_source_person(async_db, source="openalex", source_id="oa-p-1")
        authorship_id = await _a_create_authorship(async_db, pub_id, person_id)
        sa_hal = await _a_create_source_authorship(
            async_db,
            sp_hal,
            p_hal,
            source="hal",
            person_id=person_id,
            authorship_id=authorship_id,
        )
        await _a_create_source_authorship(
            async_db,
            sp_oa,
            p_oa,
            source="openalex",
            person_id=person_id,
            authorship_id=authorship_id,
        )

        assert await detach_source(async_db, sa_hal, "hal", repo=async_repo) is False

        # Authorship toujours présente
        await async_db.execute("SELECT id FROM authorships WHERE id = %s", (authorship_id,))
        assert await async_db.fetchone() is not None
        # sa_hal détachée
        await async_db.execute(
            "SELECT authorship_id FROM source_authorships WHERE id = %s", (sa_hal,)
        )
        assert (await async_db.fetchone())["authorship_id"] is None

    async def test_excluded_sources_do_not_keep_authorship_alive(self, async_db, async_repo):
        """Si les autres sources sont marquées excluded, l'authorship doit être supprimée."""
        person_id = await _a_create_person(async_db)
        pub_id = await _a_create_publication(async_db)
        sp_hal = await _a_create_source_publication(
            async_db, pub_id, source="hal", source_id="hal-1"
        )
        sp_oa = await _a_create_source_publication(
            async_db, pub_id, source="openalex", source_id="W1"
        )
        p_hal = await _a_create_source_person(async_db, source="hal", source_id="hal-p-1")
        p_oa = await _a_create_source_person(async_db, source="openalex", source_id="oa-p-1")
        authorship_id = await _a_create_authorship(async_db, pub_id, person_id)
        sa_hal = await _a_create_source_authorship(
            async_db,
            sp_hal,
            p_hal,
            source="hal",
            person_id=person_id,
            authorship_id=authorship_id,
        )
        await _a_create_source_authorship(
            async_db,
            sp_oa,
            p_oa,
            source="openalex",
            person_id=person_id,
            authorship_id=authorship_id,
            excluded=True,
        )

        assert await detach_source(async_db, sa_hal, "hal", repo=async_repo) is True

        await async_db.execute("SELECT id FROM authorships WHERE id = %s", (authorship_id,))
        assert await async_db.fetchone() is None


# ── delete_orphan_authorships ──────────────────────────────────────


class TestDeleteOrphanAuthorships:
    """delete_orphan_authorships supprime les authorships vérité d'une
    personne qui ne sont attestées par aucune source_authorship active."""

    def test_deletes_authorship_without_source(self, db, repo):
        person_id = _create_person(db)
        pub_id = _create_publication(db)
        _create_authorship(db, pub_id, person_id)

        n = delete_orphan_authorships(db, person_id, repo=repo)

        assert n == 1
        db.execute("SELECT id FROM authorships WHERE person_id = %s", (person_id,))
        assert db.fetchall() == []

    def test_keeps_authorship_with_attesting_source(self, db, repo):
        person_id = _create_person(db)
        pub_id = _create_publication(db)
        sp_id = _create_source_publication(db, pub_id)
        src_person_id = _create_source_person(db)
        authorship_id = _create_authorship(db, pub_id, person_id)
        _create_source_authorship(
            db, sp_id, src_person_id, person_id=person_id, authorship_id=authorship_id
        )

        n = delete_orphan_authorships(db, person_id, repo=repo)

        assert n == 0
        db.execute("SELECT id FROM authorships WHERE id = %s", (authorship_id,))
        assert db.fetchone() is not None

    def test_ignores_excluded_sources(self, db, repo):
        """Si la seule source attestante est excluded, l'authorship est orpheline."""
        person_id = _create_person(db)
        pub_id = _create_publication(db)
        sp_id = _create_source_publication(db, pub_id)
        src_person_id = _create_source_person(db)
        authorship_id = _create_authorship(db, pub_id, person_id)
        _create_source_authorship(
            db,
            sp_id,
            src_person_id,
            person_id=person_id,
            authorship_id=authorship_id,
            excluded=True,
        )

        n = delete_orphan_authorships(db, person_id, repo=repo)

        assert n == 1

    def test_returns_zero_when_no_authorships(self, db, repo):
        person_id = _create_person(db)
        assert delete_orphan_authorships(db, person_id, repo=repo) == 0

    def test_scoped_to_person(self, db, repo):
        """Ne touche que les authorships de la personne demandée."""
        p1 = _create_person(db, "Dupont", "Jean")
        p2 = _create_person(db, "Martin", "Sophie")
        pub_id = _create_publication(db)
        _create_authorship(db, pub_id, p1)
        pub2 = _create_publication(db, title="Autre")
        _create_authorship(db, pub2, p2)

        n = delete_orphan_authorships(db, p1, repo=repo)

        assert n == 1
        db.execute("SELECT id FROM authorships WHERE person_id = %s", (p2,))
        assert db.fetchone() is not None


# ── move_authorships_for_source ────────────────────────────────────


class TestMoveAuthorshipsForSource:
    """move_authorships_for_source repositionne une authorship vérité d'une
    publication à une autre, quand un split_bad_merges relie une
    source_authorship à une autre publication."""

    def test_raises_on_invalid_source(self, db, repo):
        with pytest.raises(ValidationError, match="Source inconnue"):
            move_authorships_for_source(db, "invalid", [1], 1, 2, repo=repo)

    def test_moves_authorship_to_target_pub(self, db, repo):
        person_id = _create_person(db)
        pub1 = _create_publication(db, title="Pub 1")
        pub2 = _create_publication(db, title="Pub 2")
        sp_id = _create_source_publication(db, pub1)
        src_person_id = _create_source_person(db)
        authorship_id = _create_authorship(db, pub1, person_id)
        sa_id = _create_source_authorship(
            db, sp_id, src_person_id, person_id=person_id, authorship_id=authorship_id
        )

        move_authorships_for_source(db, "hal", [sa_id], from_pub_id=pub1, to_pub_id=pub2, repo=repo)

        db.execute("SELECT publication_id FROM authorships WHERE id = %s", (authorship_id,))
        assert db.fetchone()["publication_id"] == pub2

    def test_noop_if_authorship_not_on_source_pub(self, db, repo):
        """Si l'authorship est déjà ailleurs, pas de changement."""
        person_id = _create_person(db)
        pub1 = _create_publication(db, title="Pub 1")
        pub2 = _create_publication(db, title="Pub 2")
        pub3 = _create_publication(db, title="Pub 3")
        sp_id = _create_source_publication(db, pub2)
        src_person_id = _create_source_person(db)
        # Authorship sur pub2 (pas pub1), la clause WHERE a.publication_id = from_pub_id bloque
        authorship_id = _create_authorship(db, pub2, person_id)
        sa_id = _create_source_authorship(
            db, sp_id, src_person_id, person_id=person_id, authorship_id=authorship_id
        )

        move_authorships_for_source(db, "hal", [sa_id], from_pub_id=pub1, to_pub_id=pub3, repo=repo)

        db.execute("SELECT publication_id FROM authorships WHERE id = %s", (authorship_id,))
        assert db.fetchone()["publication_id"] == pub2  # inchangé


# ── sync_person_id_from_source ─────────────────────────────────────


class TestSyncPersonIdFromSource:
    """sync_person_id_from_source propage le person_id d'une source vers
    l'authorship vérité, sans créer de doublon (publication, person)."""

    def test_raises_on_invalid_source(self, db, repo):
        with pytest.raises(ValidationError, match="Source inconnue"):
            sync_person_id_from_source(db, "invalid", [1], repo=repo)

    def test_sets_person_id_on_authorship(self, db, repo):
        person_id = _create_person(db)
        pub_id = _create_publication(db)
        sp_id = _create_source_publication(db, pub_id)
        src_person_id = _create_source_person(db)
        # Authorship vérité sans person_id
        authorship_id = _create_authorship(db, pub_id, None)
        sa_id = _create_source_authorship(
            db, sp_id, src_person_id, person_id=person_id, authorship_id=authorship_id
        )

        n = sync_person_id_from_source(db, "hal", [sa_id], repo=repo)

        assert n == 1
        db.execute("SELECT person_id FROM authorships WHERE id = %s", (authorship_id,))
        assert db.fetchone()["person_id"] == person_id

    def test_skips_if_already_equal(self, db, repo):
        """Si person_id est déjà égal, pas de mise à jour."""
        person_id = _create_person(db)
        pub_id = _create_publication(db)
        sp_id = _create_source_publication(db, pub_id)
        src_person_id = _create_source_person(db)
        authorship_id = _create_authorship(db, pub_id, person_id)
        sa_id = _create_source_authorship(
            db, sp_id, src_person_id, person_id=person_id, authorship_id=authorship_id
        )

        assert sync_person_id_from_source(db, "hal", [sa_id], repo=repo) == 0

    def test_skips_if_source_person_id_is_null(self, db, repo):
        """Si la source n'a pas de person_id, pas de propagation."""
        pub_id = _create_publication(db)
        sp_id = _create_source_publication(db, pub_id)
        src_person_id = _create_source_person(db)
        authorship_id = _create_authorship(db, pub_id, None)
        sa_id = _create_source_authorship(
            db, sp_id, src_person_id, person_id=None, authorship_id=authorship_id
        )

        assert sync_person_id_from_source(db, "hal", [sa_id], repo=repo) == 0

    def test_skips_on_conflict_with_existing_authorship(self, db, repo):
        """Si une autre authorship a déjà (pub, person), la sync est bloquée
        pour préserver l'unicité."""
        p1 = _create_person(db, "Dupont", "Jean")
        pub_id = _create_publication(db)
        sp_id = _create_source_publication(db, pub_id)
        src_person_id = _create_source_person(db)

        # Une authorship vérité existe déjà pour (pub, p1)
        _create_authorship(db, pub_id, p1)
        # Une autre authorship sur même pub (sans person), avec source liée à p1
        orphan = _create_authorship(db, pub_id, None)
        # Ajouter author_position pour bypass la contrainte unique
        db.execute("UPDATE authorships SET author_position = 2 WHERE id = %s", (orphan,))
        sa_id = _create_source_authorship(
            db, sp_id, src_person_id, person_id=p1, authorship_id=orphan
        )

        n = sync_person_id_from_source(db, "hal", [sa_id], repo=repo)

        assert n == 0  # bloqué par l'existence de (pub_id, p1)


# ── propagate_uca_for_addresses ────────────────────────────────────


class TestPropagateUcaForAddresses:
    """propagate_uca_for_addresses recalcule in_perimeter et structure_ids
    sur les source_authorships puis propage vers l'authorship vérité,
    après une modification sur address_structures (§2.12 : async)."""

    async def _setup_uca(self, db):
        """Monte un périmètre UCA minimal + config perimeter_persons."""
        uca_id = await _a_create_structure(db, code="UCA", name="UCA")
        await _a_create_perimeter(db, "uca", "UCA", [uca_id])
        await _a_set_config(db, "perimeter_persons", "uca")
        return uca_id

    async def test_noop_on_empty_address_ids(self, async_db, async_repo, async_perimeter_queries):
        await self._setup_uca(async_db)
        await propagate_uca_for_addresses(
            async_db, [], repo=async_repo, perimeter_queries=async_perimeter_queries
        )
        # Pas d'assertion négative utile : on vérifie juste qu'aucune exception

    async def test_noop_if_no_perimeter_configured(
        self, async_db, async_repo, async_perimeter_queries
    ):
        """Si aucun périmètre configuré, la fonction sort sans rien faire."""
        addr_id = await _a_create_address(async_db)
        # Aucun set_config perimeter_persons
        await propagate_uca_for_addresses(
            async_db, [addr_id], repo=async_repo, perimeter_queries=async_perimeter_queries
        )

    async def test_sets_in_perimeter_when_address_confirmed(
        self, async_db, async_repo, async_perimeter_queries
    ):
        uca_id = await self._setup_uca(async_db)
        person_id = await _a_create_person(async_db)
        pub_id = await _a_create_publication(async_db)
        sp_id = await _a_create_source_publication(async_db, pub_id)
        src_person_id = await _a_create_source_person(async_db)
        authorship_id = await _a_create_authorship(async_db, pub_id, person_id)
        sa_id = await _a_create_source_authorship(
            async_db, sp_id, src_person_id, person_id=person_id, authorship_id=authorship_id
        )
        addr_id = await _a_create_address(async_db)
        await _a_link_address_structure(async_db, addr_id, uca_id, is_confirmed=True)
        await _a_link_sa_address(async_db, sa_id, addr_id)

        await propagate_uca_for_addresses(
            async_db, [addr_id], repo=async_repo, perimeter_queries=async_perimeter_queries
        )

        await async_db.execute(
            "SELECT in_perimeter, structure_ids FROM source_authorships WHERE id = %s",
            (sa_id,),
        )
        sa = await async_db.fetchone()
        assert sa["in_perimeter"] is True
        assert sa["structure_ids"] == [uca_id]

        await async_db.execute(
            "SELECT in_perimeter, structure_ids FROM authorships WHERE id = %s",
            (authorship_id,),
        )
        a = await async_db.fetchone()
        assert a["in_perimeter"] is True
        assert a["structure_ids"] == [uca_id]

    async def test_unsets_in_perimeter_when_address_rejected(
        self, async_db, async_repo, async_perimeter_queries
    ):
        """Si l'adresse est rejetée (is_confirmed=False), la structure ne compte pas."""
        uca_id = await self._setup_uca(async_db)
        person_id = await _a_create_person(async_db)
        pub_id = await _a_create_publication(async_db)
        sp_id = await _a_create_source_publication(async_db, pub_id)
        src_person_id = await _a_create_source_person(async_db)
        authorship_id = await _a_create_authorship(async_db, pub_id, person_id)
        # source_authorship avec un flag in_perimeter déjà TRUE (état avant review)
        sa_id = await _a_create_source_authorship(
            async_db,
            sp_id,
            src_person_id,
            person_id=person_id,
            authorship_id=authorship_id,
            in_perimeter=True,
            structure_ids=[uca_id],
        )
        addr_id = await _a_create_address(async_db)
        await _a_link_address_structure(async_db, addr_id, uca_id, is_confirmed=False)
        await _a_link_sa_address(async_db, sa_id, addr_id)

        await propagate_uca_for_addresses(
            async_db, [addr_id], repo=async_repo, perimeter_queries=async_perimeter_queries
        )

        await async_db.execute(
            "SELECT in_perimeter, structure_ids FROM source_authorships WHERE id = %s",
            (sa_id,),
        )
        sa = await async_db.fetchone()
        assert sa["in_perimeter"] is False
        assert sa["structure_ids"] is None


# ── set_source_authorship_excluded ────────────────────────────────


class TestSetSourceAuthorshipExcluded:
    async def test_raises_on_invalid_source(self, async_db, async_repo):
        with pytest.raises(ValidationError, match="Source inconnue"):
            await set_source_authorship_excluded(async_db, 1, "invalid", True, repo=async_repo)

    async def test_raises_not_found(self, async_db, async_repo):
        with pytest.raises(NotFoundError):
            await set_source_authorship_excluded(async_db, 999999, "hal", True, repo=async_repo)

    async def test_marks_excluded(self, async_db, async_repo):
        person_id = await _a_create_person(async_db)
        pub_id = await _a_create_publication(async_db)
        sp_id = await _a_create_source_publication(async_db, pub_id)
        src_person_id = await _a_create_source_person(async_db)
        sa_id = await _a_create_source_authorship(
            async_db, sp_id, src_person_id, person_id=person_id
        )

        await set_source_authorship_excluded(async_db, sa_id, "hal", True, repo=async_repo)

        await async_db.execute("SELECT excluded FROM source_authorships WHERE id = %s", (sa_id,))
        assert (await async_db.fetchone())["excluded"] is True

    async def test_unmark_excluded_does_not_touch_authorship(self, async_db, async_repo):
        """Remettre excluded=False ne doit pas toucher à l'authorship vérité."""
        person_id = await _a_create_person(async_db)
        pub_id = await _a_create_publication(async_db)
        sp_id = await _a_create_source_publication(async_db, pub_id)
        src_person_id = await _a_create_source_person(async_db)
        authorship_id = await _a_create_authorship(async_db, pub_id, person_id)
        sa_id = await _a_create_source_authorship(
            async_db,
            sp_id,
            src_person_id,
            person_id=person_id,
            authorship_id=authorship_id,
            excluded=True,
        )

        await set_source_authorship_excluded(async_db, sa_id, "hal", False, repo=async_repo)

        await async_db.execute("SELECT id FROM authorships WHERE id = %s", (authorship_id,))
        assert await async_db.fetchone() is not None  # authorship vérité toujours là

    async def test_exclude_triggers_detach_source(self, async_db, async_repo):
        """Exclure la seule source attestante doit supprimer l'authorship vérité."""
        person_id = await _a_create_person(async_db)
        pub_id = await _a_create_publication(async_db)
        sp_id = await _a_create_source_publication(async_db, pub_id)
        src_person_id = await _a_create_source_person(async_db)
        authorship_id = await _a_create_authorship(async_db, pub_id, person_id)
        sa_id = await _a_create_source_authorship(
            async_db,
            sp_id,
            src_person_id,
            person_id=person_id,
            authorship_id=authorship_id,
        )

        await set_source_authorship_excluded(async_db, sa_id, "hal", True, repo=async_repo)

        await async_db.execute("SELECT id FROM authorships WHERE id = %s", (authorship_id,))
        assert await async_db.fetchone() is None  # authorship vérité supprimée
