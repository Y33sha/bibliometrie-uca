"""Tests de caractérisation pour services/persons.py.

Couvre link/unlink_authorship (branches source invalide), add_identifier,
detach_name_form, assign_orphan_authorship (qui couvre _ensure_truth_authorship).
merge_person est déjà testé dans test_integration.py.
"""

import pytest

from domain.errors import NotFoundError, ValidationError
from application.persons import (
    add_identifier,
    add_identifiers_from_authorships,
    assign_orphan_authorship,
    batch_assign_orphan_authorships,
    create_person,
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


def _insert_source_person(db, source="hal", source_id="hal-p-1", full_name="Jean Dupont",
                          source_ids=None):
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


def _insert_source_authorship(db, source_publication_id, source_person_id,
                              source="hal", person_id=None,
                              author_name_normalized="jean dupont",
                              excluded=False):
    db.execute(
        """
        INSERT INTO source_authorships (source, source_publication_id,
                                        source_person_id, person_id,
                                        author_name_normalized, excluded)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (source, source_publication_id, source_person_id, person_id,
         author_name_normalized, excluded),
    )
    return db.fetchone()["id"]


# ── link_authorship / unlink_authorship ────────────────────────────

class TestLinkAuthorship:
    def test_ignores_invalid_source(self, db):
        """Source inconnue → no-op silencieux (pas d'exception)."""
        link_authorship(db, 1, "invalid", 1)

    def test_sets_person_id_on_source_authorship(self, db):
        person_id = _insert_person(db)
        pub_id = _insert_publication(db)
        sp_id = _insert_source_publication(db, pub_id)
        sp_person = _insert_source_person(db)
        sa_id = _insert_source_authorship(db, sp_id, sp_person)

        link_authorship(db, person_id, "hal", sa_id)

        db.execute("SELECT person_id FROM source_authorships WHERE id = %s", (sa_id,))
        assert db.fetchone()["person_id"] == person_id

    def test_dual_write_hal_person(self, db):
        """Pour HAL avec hal_person_id, propage aussi à source_persons."""
        person_id = _insert_person(db)
        pub_id = _insert_publication(db)
        sp_id = _insert_source_publication(db, pub_id)
        sp_person = _insert_source_person(db, source_ids={"hal_person_id": 42})
        sa_id = _insert_source_authorship(db, sp_id, sp_person)

        link_authorship(db, person_id, "hal", sa_id,
                        source_person_id=sp_person, has_hal_person_id=True)

        db.execute("SELECT person_id FROM source_persons WHERE id = %s", (sp_person,))
        assert db.fetchone()["person_id"] == person_id


class TestUnlinkAuthorship:
    def test_ignores_invalid_source(self, db):
        unlink_authorship(db, 1, "invalid", 1)  # no-op silencieux

    def test_unsets_person_id(self, db):
        person_id = _insert_person(db)
        pub_id = _insert_publication(db)
        sp_id = _insert_source_publication(db, pub_id)
        sp_person = _insert_source_person(db)
        sa_id = _insert_source_authorship(db, sp_id, sp_person, person_id=person_id)

        unlink_authorship(db, person_id, "hal", sa_id)

        db.execute("SELECT person_id FROM source_authorships WHERE id = %s", (sa_id,))
        assert db.fetchone()["person_id"] is None

    def test_noop_if_person_id_mismatch(self, db):
        """Ne détache pas si l'authorship est liée à une autre personne."""
        p1 = _insert_person(db, "Dupont", "Jean")
        p2 = _insert_person(db, "Martin", "Sophie")
        pub_id = _insert_publication(db)
        sp_id = _insert_source_publication(db, pub_id)
        sp_person = _insert_source_person(db)
        sa_id = _insert_source_authorship(db, sp_id, sp_person, person_id=p1)

        unlink_authorship(db, p2, "hal", sa_id)

        db.execute("SELECT person_id FROM source_authorships WHERE id = %s", (sa_id,))
        assert db.fetchone()["person_id"] == p1  # intact


# ── add_identifier ─────────────────────────────────────────────────

class TestAddIdentifier:
    def test_inserts_new(self, db):
        person_id = _insert_person(db)
        add_identifier(db, person_id, "orcid", "0000-0001-2345-6789")
        db.execute(
            "SELECT status FROM person_identifiers WHERE id_type='orcid' AND id_value=%s",
            ("0000-0001-2345-6789",),
        )
        assert db.fetchone()["status"] == "pending"

    def test_reassigns_if_rejected(self, db):
        p1 = _insert_person(db, "A", "A")
        p2 = _insert_person(db, "B", "B")
        add_identifier(db, p1, "orcid", "0000-0001")
        db.execute(
            "UPDATE person_identifiers SET status='rejected' WHERE id_value='0000-0001'"
        )
        add_identifier(db, p2, "orcid", "0000-0001")

        db.execute(
            "SELECT person_id, status FROM person_identifiers WHERE id_value='0000-0001'"
        )
        row = db.fetchone()
        assert row["person_id"] == p2
        assert row["status"] == "pending"

    def test_does_not_override_pending(self, db):
        """Si le même identifiant existe en 'pending', on ne touche pas."""
        p1 = _insert_person(db, "A", "A")
        p2 = _insert_person(db, "B", "B")
        add_identifier(db, p1, "orcid", "0000-0001")
        add_identifier(db, p2, "orcid", "0000-0001")  # devrait rien faire

        db.execute(
            "SELECT person_id FROM person_identifiers WHERE id_value='0000-0001'"
        )
        assert db.fetchone()["person_id"] == p1

    def test_idhal_attaches_hal_source_person(self, db):
        """Ajouter un idhal à une personne rattache le compte HAL correspondant."""
        person_id = _insert_person(db)
        sp = _insert_source_person(db, source_ids={"idhal": "jean-dupont"})

        add_identifier(db, person_id, "idhal", "jean-dupont")

        db.execute("SELECT person_id FROM source_persons WHERE id = %s", (sp,))
        assert db.fetchone()["person_id"] == person_id


class TestRemoveIdentifier:
    def test_removes_existing(self, db):
        p = _insert_person(db)
        add_identifier(db, p, "orcid", "0000-0001")
        remove_identifier(db, p, "orcid", "0000-0001")
        db.execute(
            "SELECT id FROM person_identifiers WHERE id_value = '0000-0001'"
        )
        assert db.fetchone() is None

    def test_raises_not_found(self, db):
        p = _insert_person(db)
        with pytest.raises(NotFoundError):
            remove_identifier(db, p, "orcid", "unknown")


class TestUpdateIdentifierStatus:
    def test_sets_status(self, db):
        p = _insert_person(db)
        add_identifier(db, p, "orcid", "0000-0001")
        db.execute("SELECT id FROM person_identifiers WHERE id_value='0000-0001'")
        ident_id = db.fetchone()["id"]

        row = update_identifier_status(db, ident_id, "confirmed")

        assert row["status"] == "confirmed"

    def test_raises_not_found(self, db):
        with pytest.raises(NotFoundError):
            update_identifier_status(db, 999999, "confirmed")


class TestReassignIdentifier:
    def test_reassigns(self, db):
        p1 = _insert_person(db, "A", "A")
        p2 = _insert_person(db, "B", "B")
        add_identifier(db, p1, "orcid", "0000-0001")
        db.execute("SELECT id FROM person_identifiers WHERE id_value='0000-0001'")
        ident_id = db.fetchone()["id"]

        reassign_identifier(db, ident_id, p2)

        db.execute(
            "SELECT person_id, status::text AS status FROM person_identifiers WHERE id = %s",
            (ident_id,),
        )
        row = db.fetchone()
        assert row["person_id"] == p2
        assert row["status"] == "pending"

    def test_raises_not_found(self, db):
        p = _insert_person(db)
        with pytest.raises(NotFoundError):
            reassign_identifier(db, 999999, p)


class TestSetRejected:
    def test_marks_rejected(self, db):
        p = _insert_person(db)
        set_rejected(db, p, True)
        db.execute("SELECT rejected FROM persons WHERE id = %s", (p,))
        assert db.fetchone()["rejected"] is True

    def test_unmarks(self, db):
        p = _insert_person(db)
        set_rejected(db, p, True)
        set_rejected(db, p, False)
        db.execute("SELECT rejected FROM persons WHERE id = %s", (p,))
        assert db.fetchone()["rejected"] is False

    def test_raises_not_found(self, db):
        with pytest.raises(NotFoundError):
            set_rejected(db, 999999, True)


class TestUpdateName:
    def test_updates_name_and_refreshes_forms(self, db):
        p = create_person(db, "Dupont", "Jean")
        # La forme 'dupont jean' existe après create_person
        db.execute("SELECT id FROM person_name_forms WHERE name_form = 'dupont jean'")
        assert db.fetchone() is not None

        update_name(db, p, "Martin", "Sophie")

        db.execute("SELECT last_name, first_name FROM persons WHERE id = %s", (p,))
        row = db.fetchone()
        assert row["last_name"] == "Martin"
        assert row["first_name"] == "Sophie"

        # Nouvelle forme créée
        db.execute("SELECT id FROM person_name_forms WHERE name_form = 'martin sophie'")
        assert db.fetchone() is not None

    def test_raises_not_found(self, db):
        with pytest.raises(NotFoundError):
            update_name(db, 999999, "X", "X")


# ── batch_assign_orphan_authorships ─────────────────────────────────

class TestBatchAssignOrphanAuthorships:
    def _setup_uca(self, db):
        import json
        db.execute(
            """
            INSERT INTO structures (code, name, structure_type)
            VALUES ('UCA', 'UCA', 'universite'::structure_type)
            RETURNING id
            """
        )
        uca = db.fetchone()["id"]
        db.execute(
            "INSERT INTO perimeters (code, name, structure_ids) VALUES ('uca', 'UCA', %s)",
            ([uca],),
        )
        db.execute(
            "INSERT INTO config (key, value) VALUES ('perimeter_persons', %s::jsonb)",
            (json.dumps("uca"),),
        )

    def test_empty_list_returns_zero(self, db):
        self._setup_uca(db)
        person_id = _insert_person(db)
        assert batch_assign_orphan_authorships(db, person_id, []) == 0

    def test_assigns_and_creates_truth(self, db):
        self._setup_uca(db)
        person_id = _insert_person(db)
        pub_id = _insert_publication(db)
        sp_hal = _insert_source_publication(db, pub_id, source="hal", source_id="h-1")
        sp_oa = _insert_source_publication(db, pub_id, source="openalex", source_id="W1")
        sp_person_hal = _insert_source_person(db, source="hal", source_id="hal-p-1")
        sp_person_oa = _insert_source_person(db, source="openalex", source_id="oa-p-1")
        sa1 = _insert_source_authorship(db, sp_hal, sp_person_hal, source="hal",
                                        author_name_normalized="jean dupont")
        sa2 = _insert_source_authorship(db, sp_oa, sp_person_oa, source="openalex",
                                        author_name_normalized="jean dupont")

        assigned = batch_assign_orphan_authorships(db, person_id, [sa1, sa2])

        assert assigned == 2
        # authorship vérité créée pour la publication
        db.execute(
            "SELECT id FROM authorships WHERE publication_id = %s AND person_id = %s",
            (pub_id, person_id),
        )
        assert db.fetchone() is not None
        # FK posée sur les 2 source_authorships
        db.execute(
            "SELECT authorship_id FROM source_authorships WHERE id = ANY(%s)",
            ([sa1, sa2],),
        )
        rows = db.fetchall()
        assert all(r["authorship_id"] is not None for r in rows)

    def test_skips_already_assigned(self, db):
        self._setup_uca(db)
        p1 = _insert_person(db, "A", "A")
        p2 = _insert_person(db, "B", "B")
        pub_id = _insert_publication(db)
        sp_id = _insert_source_publication(db, pub_id)
        sp_person = _insert_source_person(db)
        # sa1 déjà assignée à p1
        sa1 = _insert_source_authorship(db, sp_id, sp_person, person_id=p1)

        assigned = batch_assign_orphan_authorships(db, p2, [sa1])

        assert assigned == 0  # pas d'orpheline à rattacher
        db.execute("SELECT person_id FROM source_authorships WHERE id = %s", (sa1,))
        assert db.fetchone()["person_id"] == p1  # inchangé


# ── detach_authorships ─────────────────────────────────────────────

class TestDetachAuthorships:
    def test_detaches_and_removes_truth_if_orphan(self, db):
        person_id = _insert_person(db)
        pub_id = _insert_publication(db)
        sp_id = _insert_source_publication(db, pub_id)
        sp_person = _insert_source_person(db)
        auth_id = db.execute(
            "INSERT INTO authorships (publication_id, person_id) VALUES (%s, %s) RETURNING id",
            (pub_id, person_id),
        )
        db.execute(
            "SELECT id FROM authorships WHERE publication_id = %s AND person_id = %s",
            (pub_id, person_id),
        )
        auth_id = db.fetchone()["id"]
        sa_id = _insert_source_authorship(db, sp_id, sp_person, person_id=person_id)

        result = detach_authorships(
            db, person_id,
            authorships=[{"source": "hal", "authorship_id": sa_id}],
        )

        assert result["detached"] == 1
        assert result["deleted_authorships"] == 1
        # source_authorship détaché
        db.execute("SELECT person_id FROM source_authorships WHERE id = %s", (sa_id,))
        assert db.fetchone()["person_id"] is None
        # authorship vérité supprimée (orpheline)
        db.execute("SELECT id FROM authorships WHERE id = %s", (auth_id,))
        assert db.fetchone() is None

    def test_cleans_name_form_when_no_remaining(self, db):
        person_id = create_person(db, "Dupont", "Jean")
        # add_name_form simulé via create_person

        # Pas de source_authorship portant "dupont jean" → la forme est nettoyée
        result = detach_authorships(db, person_id, authorships=[],
                                     name_form="dupont jean")
        assert result["cleaned_form"] is True

        db.execute("SELECT id FROM person_name_forms WHERE name_form = 'dupont jean'")
        # La forme a été retirée ou la person_id a été enlevée
        row = db.fetchone()
        if row:
            db.execute("SELECT person_ids FROM person_name_forms WHERE name_form = 'dupont jean'")
            assert person_id not in (db.fetchone()["person_ids"] or [])

    def test_keeps_name_form_if_another_authorship_uses_it(self, db):
        person_id = create_person(db, "Dupont", "Jean")
        pub_id = _insert_publication(db)
        sp_id = _insert_source_publication(db, pub_id)
        sp_person = _insert_source_person(db)
        # source_authorship portant la forme "dupont jean"
        _insert_source_authorship(db, sp_id, sp_person, person_id=person_id,
                                  author_name_normalized="dupont jean")

        result = detach_authorships(db, person_id, authorships=[],
                                     name_form="dupont jean")

        assert result["cleaned_form"] is False


class TestMarkDistinctPersons:
    def test_inserts_ordered_pair(self, db):
        p1 = _insert_person(db, "A", "A")
        p2 = _insert_person(db, "B", "B")
        mark_distinct(db, p2, p1)  # ordre inverse
        db.execute(
            "SELECT COUNT(*) AS n FROM distinct_persons WHERE person_id_a = %s AND person_id_b = %s",
            (min(p1, p2), max(p1, p2)),
        )
        assert db.fetchone()["n"] == 1

    def test_idempotent(self, db):
        p1 = _insert_person(db, "A", "A")
        p2 = _insert_person(db, "B", "B")
        mark_distinct(db, p1, p2)
        mark_distinct(db, p1, p2)  # ON CONFLICT DO NOTHING
        db.execute(
            "SELECT COUNT(*) AS n FROM distinct_persons WHERE person_id_a = %s AND person_id_b = %s",
            (min(p1, p2), max(p1, p2)),
        )
        assert db.fetchone()["n"] == 1


class TestAddIdentifiersFromAuthorships:
    def test_adds_orcid_idhal_idref_once(self, db):
        person_id = _insert_person(db)
        authorships = [
            {"source": "hal", "orcid": "0000-0001", "idhal": "jdupont"},
            {"source": "scanr", "orcid": "0000-0001", "idref": "123456"},  # orcid dédupliqué
        ]
        add_identifiers_from_authorships(db, person_id, authorships)

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
    def test_removes_person_from_form(self, db):
        p1 = create_person(db, "Dupont", "Jean")
        p2 = create_person(db, "Dupont", "Jean")  # même forme 'dupont jean'

        detach_name_form(db, p1, "dupont jean")

        db.execute(
            "SELECT person_ids FROM person_name_forms WHERE name_form = 'dupont jean'"
        )
        row = db.fetchone()
        assert row is not None
        assert p1 not in row["person_ids"]
        assert p2 in row["person_ids"]

    def test_deletes_form_when_last_person_detached(self, db):
        person_id = create_person(db, "Unique", "Name")

        detach_name_form(db, person_id, "name unique")

        db.execute(
            "SELECT id FROM person_name_forms WHERE name_form = 'name unique'"
        )
        assert db.fetchone() is None


# ── assign_orphan_authorship (+ _ensure_truth_authorship) ──────────

class TestAssignOrphanAuthorship:
    def _setup(self, db):
        """Monte un périmètre UCA minimal (nécessaire pour _ensure_truth_authorship)."""
        import json
        db.execute(
            """
            INSERT INTO structures (code, name, structure_type)
            VALUES ('UCA', 'UCA', 'universite'::structure_type)
            RETURNING id
            """
        )
        uca_id = db.fetchone()["id"]
        db.execute(
            "INSERT INTO perimeters (code, name, structure_ids) VALUES ('uca', 'UCA', %s)",
            ([uca_id],),
        )
        db.execute(
            "INSERT INTO config (key, value) VALUES ('perimeter_persons', %s::jsonb)",
            (json.dumps("uca"),),
        )
        return uca_id

    def test_raises_on_invalid_source(self, db):
        with pytest.raises(ValidationError, match="Source inconnue"):
            assign_orphan_authorship(db, 1, "invalid", 1)

    def test_returns_false_if_already_assigned(self, db):
        """Si l'authorship a déjà un person_id, l'UPDATE ne matche pas."""
        self._setup(db)
        person_id = _insert_person(db)
        other_id = _insert_person(db, "Other", "Author")
        pub_id = _insert_publication(db)
        sp_id = _insert_source_publication(db, pub_id)
        sp_person = _insert_source_person(db)
        sa_id = _insert_source_authorship(db, sp_id, sp_person, person_id=other_id)

        assert assign_orphan_authorship(db, person_id, "hal", sa_id) is False

    def test_assigns_and_creates_truth_authorship(self, db):
        self._setup(db)
        person_id = _insert_person(db)
        pub_id = _insert_publication(db)
        sp_id = _insert_source_publication(db, pub_id)
        sp_person = _insert_source_person(db)
        sa_id = _insert_source_authorship(db, sp_id, sp_person)  # orpheline

        result = assign_orphan_authorship(db, person_id, "hal", sa_id)

        assert result is True
        # person_id assigné sur source_authorship
        db.execute("SELECT person_id, authorship_id FROM source_authorships WHERE id = %s", (sa_id,))
        row = db.fetchone()
        assert row["person_id"] == person_id
        assert row["authorship_id"] is not None

        # authorship vérité créée
        db.execute(
            "SELECT id FROM authorships WHERE publication_id = %s AND person_id = %s",
            (pub_id, person_id),
        )
        assert db.fetchone() is not None

    def test_skips_name_form_if_excluded(self, db):
        """Si la source authorship est excluded, pas d'ajout de name_form."""
        self._setup(db)
        person_id = _insert_person(db, "Zzz", "Zzz")  # forme 'zzz' / 'zzz zzz'
        pub_id = _insert_publication(db)
        sp_id = _insert_source_publication(db, pub_id)
        sp_person = _insert_source_person(db)
        sa_id = _insert_source_authorship(
            db, sp_id, sp_person,
            author_name_normalized="other name",
            excluded=True,
        )

        assign_orphan_authorship(db, person_id, "hal", sa_id)

        # Aucune nouvelle name_form 'other name' n'a été créée
        db.execute(
            "SELECT id FROM person_name_forms WHERE name_form = 'other name'"
        )
        assert db.fetchone() is None
