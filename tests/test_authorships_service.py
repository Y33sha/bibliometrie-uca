"""Tests de caractérisation pour services/authorships.py.

Documentent le comportement actuel des fonctions du service pour protéger
contre les régressions lors de refactos ultérieurs.
"""

import pytest

from services.authorships import (
    delete_orphan_authorships,
    detach_source,
    exclude_authorship,
)


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
):
    db.execute(
        """
        INSERT INTO source_authorships (source, source_publication_id,
                                        source_person_id, person_id,
                                        authorship_id, excluded)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (source, source_publication_id, source_person_id, person_id, authorship_id, excluded),
    )
    return db.fetchone()["id"]


# ── exclude_authorship ─────────────────────────────────────────────

class TestExcludeAuthorship:
    """exclude_authorship marque l'authorship vérité comme excluded et
    détache les source_authorships qui y référaient."""

    def test_marks_excluded_and_detaches_sources(self, db):
        person_id = _create_person(db)
        pub_id = _create_publication(db)
        sp_id = _create_source_publication(db, pub_id)
        src_person_id = _create_source_person(db)
        authorship_id = _create_authorship(db, pub_id, person_id)
        sa_id = _create_source_authorship(
            db, sp_id, src_person_id, person_id=person_id, authorship_id=authorship_id
        )

        result = exclude_authorship(db, authorship_id)

        assert result is not None
        assert result["excluded"] is True

        # Source détachée : person_id et authorship_id remis à NULL
        db.execute(
            "SELECT person_id, authorship_id FROM source_authorships WHERE id = %s",
            (sa_id,),
        )
        row = db.fetchone()
        assert row["person_id"] is None
        assert row["authorship_id"] is None

    def test_returns_none_if_not_found(self, db):
        assert exclude_authorship(db, 999999) is None

    def test_does_not_detach_unrelated_sources(self, db):
        """Les sources d'autres personnes sur la même pub ne sont pas touchées."""
        pub_id = _create_publication(db)
        sp_id = _create_source_publication(db, pub_id)

        p1 = _create_person(db, "Dupont", "Jean")
        p2 = _create_person(db, "Martin", "Sophie")
        sp1 = _create_source_person(db, source_id="hal-p-1")
        sp2 = _create_source_person(db, source_id="hal-p-2")
        a1 = _create_authorship(db, pub_id, p1)
        a2 = _create_authorship(db, pub_id, p2)
        sa1 = _create_source_authorship(db, sp_id, sp1, person_id=p1, authorship_id=a1)
        sa2 = _create_source_authorship(db, sp_id, sp2, person_id=p2, authorship_id=a2)

        exclude_authorship(db, a1)

        # sa1 détachée
        db.execute("SELECT person_id FROM source_authorships WHERE id = %s", (sa1,))
        assert db.fetchone()["person_id"] is None
        # sa2 intacte
        db.execute("SELECT person_id FROM source_authorships WHERE id = %s", (sa2,))
        assert db.fetchone()["person_id"] == p2


# ── detach_source ──────────────────────────────────────────────────

class TestDetachSource:
    """detach_source retire le lien FK d'une source_authorship vers l'authorship
    vérité. Supprime l'authorship vérité si plus aucune source ne l'atteste."""

    def test_raises_on_invalid_source(self, db):
        with pytest.raises(ValueError, match="Source inconnue"):
            detach_source(db, 1, "invalid_source")

    def test_returns_false_if_no_authorship_linked(self, db):
        pub_id = _create_publication(db)
        sp_id = _create_source_publication(db, pub_id)
        src_person_id = _create_source_person(db)
        # source_authorship sans authorship_id
        sa_id = _create_source_authorship(db, sp_id, src_person_id)

        assert detach_source(db, sa_id, "hal") is False

    def test_deletes_authorship_when_last_source_removed(self, db):
        """Une seule source atteste l'authorship → le détacher supprime l'authorship."""
        person_id = _create_person(db)
        pub_id = _create_publication(db)
        sp_id = _create_source_publication(db, pub_id)
        src_person_id = _create_source_person(db)
        authorship_id = _create_authorship(db, pub_id, person_id)
        sa_id = _create_source_authorship(
            db, sp_id, src_person_id, person_id=person_id, authorship_id=authorship_id
        )

        assert detach_source(db, sa_id, "hal") is True

        db.execute("SELECT id FROM authorships WHERE id = %s", (authorship_id,))
        assert db.fetchone() is None

    def test_keeps_authorship_when_other_sources_remain(self, db):
        """Deux sources attestent l'authorship → détacher une garde l'authorship."""
        person_id = _create_person(db)
        pub_id = _create_publication(db)
        sp_hal = _create_source_publication(db, pub_id, source="hal", source_id="hal-1")
        sp_oa = _create_source_publication(db, pub_id, source="openalex", source_id="W1")
        p_hal = _create_source_person(db, source="hal", source_id="hal-p-1")
        p_oa = _create_source_person(db, source="openalex", source_id="oa-p-1")
        authorship_id = _create_authorship(db, pub_id, person_id)
        sa_hal = _create_source_authorship(
            db, sp_hal, p_hal, source="hal", person_id=person_id, authorship_id=authorship_id
        )
        _create_source_authorship(
            db, sp_oa, p_oa, source="openalex", person_id=person_id, authorship_id=authorship_id
        )

        assert detach_source(db, sa_hal, "hal") is False

        # Authorship toujours présente
        db.execute("SELECT id FROM authorships WHERE id = %s", (authorship_id,))
        assert db.fetchone() is not None
        # sa_hal détachée
        db.execute("SELECT authorship_id FROM source_authorships WHERE id = %s", (sa_hal,))
        assert db.fetchone()["authorship_id"] is None

    def test_excluded_sources_do_not_keep_authorship_alive(self, db):
        """Si les autres sources sont marquées excluded, l'authorship doit être supprimée."""
        person_id = _create_person(db)
        pub_id = _create_publication(db)
        sp_hal = _create_source_publication(db, pub_id, source="hal", source_id="hal-1")
        sp_oa = _create_source_publication(db, pub_id, source="openalex", source_id="W1")
        p_hal = _create_source_person(db, source="hal", source_id="hal-p-1")
        p_oa = _create_source_person(db, source="openalex", source_id="oa-p-1")
        authorship_id = _create_authorship(db, pub_id, person_id)
        sa_hal = _create_source_authorship(
            db, sp_hal, p_hal, source="hal", person_id=person_id, authorship_id=authorship_id
        )
        _create_source_authorship(
            db, sp_oa, p_oa, source="openalex", person_id=person_id,
            authorship_id=authorship_id, excluded=True,
        )

        assert detach_source(db, sa_hal, "hal") is True

        db.execute("SELECT id FROM authorships WHERE id = %s", (authorship_id,))
        assert db.fetchone() is None


# ── delete_orphan_authorships ──────────────────────────────────────

class TestDeleteOrphanAuthorships:
    """delete_orphan_authorships supprime les authorships vérité d'une
    personne qui ne sont attestées par aucune source_authorship active."""

    def test_deletes_authorship_without_source(self, db):
        person_id = _create_person(db)
        pub_id = _create_publication(db)
        _create_authorship(db, pub_id, person_id)

        n = delete_orphan_authorships(db, person_id)

        assert n == 1
        db.execute(
            "SELECT id FROM authorships WHERE person_id = %s", (person_id,)
        )
        assert db.fetchall() == []

    def test_keeps_authorship_with_attesting_source(self, db):
        person_id = _create_person(db)
        pub_id = _create_publication(db)
        sp_id = _create_source_publication(db, pub_id)
        src_person_id = _create_source_person(db)
        authorship_id = _create_authorship(db, pub_id, person_id)
        _create_source_authorship(
            db, sp_id, src_person_id, person_id=person_id, authorship_id=authorship_id
        )

        n = delete_orphan_authorships(db, person_id)

        assert n == 0
        db.execute("SELECT id FROM authorships WHERE id = %s", (authorship_id,))
        assert db.fetchone() is not None

    def test_ignores_excluded_sources(self, db):
        """Si la seule source attestante est excluded, l'authorship est orpheline."""
        person_id = _create_person(db)
        pub_id = _create_publication(db)
        sp_id = _create_source_publication(db, pub_id)
        src_person_id = _create_source_person(db)
        authorship_id = _create_authorship(db, pub_id, person_id)
        _create_source_authorship(
            db, sp_id, src_person_id, person_id=person_id,
            authorship_id=authorship_id, excluded=True,
        )

        n = delete_orphan_authorships(db, person_id)

        assert n == 1

    def test_returns_zero_when_no_authorships(self, db):
        person_id = _create_person(db)
        assert delete_orphan_authorships(db, person_id) == 0

    def test_scoped_to_person(self, db):
        """Ne touche que les authorships de la personne demandée."""
        p1 = _create_person(db, "Dupont", "Jean")
        p2 = _create_person(db, "Martin", "Sophie")
        pub_id = _create_publication(db)
        _create_authorship(db, pub_id, p1)
        pub2 = _create_publication(db, title="Autre")
        _create_authorship(db, pub2, p2)

        n = delete_orphan_authorships(db, p1)

        assert n == 1
        db.execute("SELECT id FROM authorships WHERE person_id = %s", (p2,))
        assert db.fetchone() is not None
