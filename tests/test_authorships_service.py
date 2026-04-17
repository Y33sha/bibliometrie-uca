"""Tests de caractérisation pour services/authorships.py.

Documentent le comportement actuel des fonctions du service pour protéger
contre les régressions lors de refactos ultérieurs.
"""

import json

import pytest

from services.authorships import (
    delete_orphan_authorships,
    detach_source,
    exclude_authorship,
    move_authorships_for_source,
    propagate_uca_for_addresses,
    set_source_authorship_excluded,
    sync_person_id_from_source,
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
        (source, source_publication_id, source_person_id, person_id,
         authorship_id, excluded, in_perimeter, structure_ids),
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


# ── move_authorships_for_source ────────────────────────────────────

class TestMoveAuthorshipsForSource:
    """move_authorships_for_source repositionne une authorship vérité d'une
    publication à une autre, quand un split_bad_merges relie une
    source_authorship à une autre publication."""

    def test_raises_on_invalid_source(self, db):
        with pytest.raises(ValueError, match="Source inconnue"):
            move_authorships_for_source(db, "invalid", [1], 1, 2)

    def test_moves_authorship_to_target_pub(self, db):
        person_id = _create_person(db)
        pub1 = _create_publication(db, title="Pub 1")
        pub2 = _create_publication(db, title="Pub 2")
        sp_id = _create_source_publication(db, pub1)
        src_person_id = _create_source_person(db)
        authorship_id = _create_authorship(db, pub1, person_id)
        sa_id = _create_source_authorship(
            db, sp_id, src_person_id, person_id=person_id, authorship_id=authorship_id
        )

        move_authorships_for_source(db, "hal", [sa_id], from_pub_id=pub1, to_pub_id=pub2)

        db.execute("SELECT publication_id FROM authorships WHERE id = %s", (authorship_id,))
        assert db.fetchone()["publication_id"] == pub2

    def test_noop_if_authorship_not_on_source_pub(self, db):
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

        move_authorships_for_source(db, "hal", [sa_id], from_pub_id=pub1, to_pub_id=pub3)

        db.execute("SELECT publication_id FROM authorships WHERE id = %s", (authorship_id,))
        assert db.fetchone()["publication_id"] == pub2  # inchangé


# ── sync_person_id_from_source ─────────────────────────────────────

class TestSyncPersonIdFromSource:
    """sync_person_id_from_source propage le person_id d'une source vers
    l'authorship vérité, sans créer de doublon (publication, person)."""

    def test_raises_on_invalid_source(self, db):
        with pytest.raises(ValueError, match="Source inconnue"):
            sync_person_id_from_source(db, "invalid", [1])

    def test_sets_person_id_on_authorship(self, db):
        person_id = _create_person(db)
        pub_id = _create_publication(db)
        sp_id = _create_source_publication(db, pub_id)
        src_person_id = _create_source_person(db)
        # Authorship vérité sans person_id
        authorship_id = _create_authorship(db, pub_id, None)
        sa_id = _create_source_authorship(
            db, sp_id, src_person_id, person_id=person_id, authorship_id=authorship_id
        )

        n = sync_person_id_from_source(db, "hal", [sa_id])

        assert n == 1
        db.execute("SELECT person_id FROM authorships WHERE id = %s", (authorship_id,))
        assert db.fetchone()["person_id"] == person_id

    def test_skips_if_already_equal(self, db):
        """Si person_id est déjà égal, pas de mise à jour."""
        person_id = _create_person(db)
        pub_id = _create_publication(db)
        sp_id = _create_source_publication(db, pub_id)
        src_person_id = _create_source_person(db)
        authorship_id = _create_authorship(db, pub_id, person_id)
        sa_id = _create_source_authorship(
            db, sp_id, src_person_id, person_id=person_id, authorship_id=authorship_id
        )

        assert sync_person_id_from_source(db, "hal", [sa_id]) == 0

    def test_skips_if_source_person_id_is_null(self, db):
        """Si la source n'a pas de person_id, pas de propagation."""
        pub_id = _create_publication(db)
        sp_id = _create_source_publication(db, pub_id)
        src_person_id = _create_source_person(db)
        authorship_id = _create_authorship(db, pub_id, None)
        sa_id = _create_source_authorship(
            db, sp_id, src_person_id, person_id=None, authorship_id=authorship_id
        )

        assert sync_person_id_from_source(db, "hal", [sa_id]) == 0

    def test_skips_on_conflict_with_existing_authorship(self, db):
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
        db.execute(
            "UPDATE authorships SET author_position = 2 WHERE id = %s", (orphan,)
        )
        sa_id = _create_source_authorship(
            db, sp_id, src_person_id, person_id=p1, authorship_id=orphan
        )

        n = sync_person_id_from_source(db, "hal", [sa_id])

        assert n == 0  # bloqué par l'existence de (pub_id, p1)


# ── propagate_uca_for_addresses ────────────────────────────────────

class TestPropagateUcaForAddresses:
    """propagate_uca_for_addresses recalcule in_perimeter et structure_ids
    sur les source_authorships puis propage vers l'authorship vérité,
    après une modification sur address_structures."""

    def _setup_uca(self, db):
        """Monte un périmètre UCA minimal + config perimeter_persons."""
        uca_id = _create_structure(db, code="UCA", name="UCA")
        _create_perimeter(db, "uca", "UCA", [uca_id])
        _set_config(db, "perimeter_persons", "uca")
        return uca_id

    def test_noop_on_empty_address_ids(self, db):
        self._setup_uca(db)
        propagate_uca_for_addresses(db, [])
        # Pas d'assertion négative utile : on vérifie juste qu'aucune exception

    def test_noop_if_no_perimeter_configured(self, db):
        """Si aucun périmètre configuré, la fonction sort sans rien faire."""
        addr_id = _create_address(db)
        # Aucun set_config perimeter_persons
        propagate_uca_for_addresses(db, [addr_id])

    def test_sets_in_perimeter_when_address_confirmed(self, db):
        uca_id = self._setup_uca(db)
        person_id = _create_person(db)
        pub_id = _create_publication(db)
        sp_id = _create_source_publication(db, pub_id)
        src_person_id = _create_source_person(db)
        authorship_id = _create_authorship(db, pub_id, person_id)
        sa_id = _create_source_authorship(
            db, sp_id, src_person_id, person_id=person_id, authorship_id=authorship_id
        )
        addr_id = _create_address(db)
        _link_address_structure(db, addr_id, uca_id, is_confirmed=True)
        _link_sa_address(db, sa_id, addr_id)

        propagate_uca_for_addresses(db, [addr_id])

        db.execute(
            "SELECT in_perimeter, structure_ids FROM source_authorships WHERE id = %s",
            (sa_id,),
        )
        sa = db.fetchone()
        assert sa["in_perimeter"] is True
        assert sa["structure_ids"] == [uca_id]

        db.execute(
            "SELECT in_perimeter, structure_ids FROM authorships WHERE id = %s",
            (authorship_id,),
        )
        a = db.fetchone()
        assert a["in_perimeter"] is True
        assert a["structure_ids"] == [uca_id]

    def test_unsets_in_perimeter_when_address_rejected(self, db):
        """Si l'adresse est rejetée (is_confirmed=False), la structure ne compte pas."""
        uca_id = self._setup_uca(db)
        person_id = _create_person(db)
        pub_id = _create_publication(db)
        sp_id = _create_source_publication(db, pub_id)
        src_person_id = _create_source_person(db)
        authorship_id = _create_authorship(db, pub_id, person_id)
        # source_authorship avec un flag in_perimeter déjà TRUE (état avant review)
        sa_id = _create_source_authorship(
            db, sp_id, src_person_id, person_id=person_id,
            authorship_id=authorship_id, in_perimeter=True, structure_ids=[uca_id],
        )
        addr_id = _create_address(db)
        _link_address_structure(db, addr_id, uca_id, is_confirmed=False)
        _link_sa_address(db, sa_id, addr_id)

        propagate_uca_for_addresses(db, [addr_id])

        db.execute(
            "SELECT in_perimeter, structure_ids FROM source_authorships WHERE id = %s",
            (sa_id,),
        )
        sa = db.fetchone()
        assert sa["in_perimeter"] is False
        assert sa["structure_ids"] is None


# ── set_source_authorship_excluded ────────────────────────────────

class TestSetSourceAuthorshipExcluded:
    def test_raises_on_invalid_source(self, db):
        with pytest.raises(ValueError, match="Source inconnue"):
            set_source_authorship_excluded(db, 1, "invalid", True)

    def test_returns_false_if_not_found(self, db):
        assert set_source_authorship_excluded(db, 999999, "hal", True) is False

    def test_marks_excluded(self, db):
        person_id = _create_person(db)
        pub_id = _create_publication(db)
        sp_id = _create_source_publication(db, pub_id)
        src_person_id = _create_source_person(db)
        sa_id = _create_source_authorship(db, sp_id, src_person_id, person_id=person_id)

        assert set_source_authorship_excluded(db, sa_id, "hal", True) is True

        db.execute("SELECT excluded FROM source_authorships WHERE id = %s", (sa_id,))
        assert db.fetchone()["excluded"] is True

    def test_unmark_excluded_does_not_touch_authorship(self, db):
        """Remettre excluded=False ne doit pas toucher à l'authorship vérité."""
        person_id = _create_person(db)
        pub_id = _create_publication(db)
        sp_id = _create_source_publication(db, pub_id)
        src_person_id = _create_source_person(db)
        authorship_id = _create_authorship(db, pub_id, person_id)
        sa_id = _create_source_authorship(
            db, sp_id, src_person_id, person_id=person_id,
            authorship_id=authorship_id, excluded=True,
        )

        set_source_authorship_excluded(db, sa_id, "hal", False)

        db.execute("SELECT id FROM authorships WHERE id = %s", (authorship_id,))
        assert db.fetchone() is not None  # authorship vérité toujours là

    def test_exclude_triggers_detach_source(self, db):
        """Exclure la seule source attestante doit supprimer l'authorship vérité."""
        person_id = _create_person(db)
        pub_id = _create_publication(db)
        sp_id = _create_source_publication(db, pub_id)
        src_person_id = _create_source_person(db)
        authorship_id = _create_authorship(db, pub_id, person_id)
        sa_id = _create_source_authorship(
            db, sp_id, src_person_id, person_id=person_id, authorship_id=authorship_id
        )

        set_source_authorship_excluded(db, sa_id, "hal", True)

        db.execute("SELECT id FROM authorships WHERE id = %s", (authorship_id,))
        assert db.fetchone() is None  # authorship vérité supprimée
