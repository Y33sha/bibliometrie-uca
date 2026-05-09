"""Tests de caractérisation pour application/persons.py.

Couvre link/unlink_authorship (branches source invalide), add_identifier,
detach_name_form, assign_orphan_authorship (qui couvre _ensure_truth_authorship),
merge_person, etc.
"""

import json

import pytest
from sqlalchemy import text

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
from domain.errors import NotFoundError, ValidationError
from infrastructure.repositories import (
    authorship_repository,
    person_repository,
)


@pytest.fixture
def repo(db):
    """Repository sync via cur psycopg (pipeline-style tests)."""
    return person_repository(db)


@pytest.fixture
def sa_repo(sa_sync_conn):
    """Repository sync via Connection SA (API-style tests)."""
    return person_repository(sa_sync_conn)


@pytest.fixture
def authorship_repo(sa_sync_conn):
    return authorship_repository(sa_sync_conn)


# ── Helpers psycopg cur (pipeline-style) ─────────────────────────


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


# ── Helpers Connection SA (API-style) ────────────────────────────


def _sa_insert_person(conn, last="Dupont", first="Jean"):
    row = conn.execute(
        text(
            "INSERT INTO persons (last_name, first_name, "
            "                     last_name_normalized, first_name_normalized) "
            "VALUES (:l, :f, lower(:l), lower(:f)) RETURNING id"
        ),
        {"l": last, "f": first},
    ).one()
    return row.id


def _sa_insert_publication(conn, title="Test"):
    row = conn.execute(
        text("INSERT INTO publications (title, pub_year) VALUES (:t, 2024) RETURNING id"),
        {"t": title},
    ).one()
    return row.id


def _sa_insert_source_publication(conn, publication_id, source="hal", source_id="hal-1"):
    row = conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, publication_id) "
            "VALUES (:s, :sid, 'Test', :pid) RETURNING id"
        ),
        {"s": source, "sid": source_id, "pid": publication_id},
    ).one()
    return row.id


def _sa_insert_source_person(
    conn, source="hal", source_id="hal-p-1", full_name="Jean Dupont", source_ids=None
):
    row = conn.execute(
        text(
            "INSERT INTO source_persons (source, source_id, full_name, source_ids) "
            "VALUES (:s, :sid, :n, CAST(:si AS jsonb)) RETURNING id"
        ),
        {
            "s": source,
            "sid": source_id,
            "n": full_name,
            "si": json.dumps(source_ids) if source_ids else None,
        },
    ).one()
    return row.id


def _sa_insert_source_authorship(
    conn,
    source_publication_id,
    source_person_id,
    source="hal",
    person_id=None,
    author_name_normalized="jean dupont",
    excluded=False,
):
    row = conn.execute(
        text(
            "INSERT INTO source_authorships (source, source_publication_id, "
            "                                source_person_id, person_id, "
            "                                author_name_normalized, excluded) "
            "VALUES (:s, :spid, :sper, :pid, :anf, :ex) RETURNING id"
        ),
        {
            "s": source,
            "spid": source_publication_id,
            "sper": source_person_id,
            "pid": person_id,
            "anf": author_name_normalized,
            "ex": excluded,
        },
    ).one()
    return row.id


def _sa_setup_uca(conn):
    """Périmètre UCA minimal pour les tests qui dépendent de in_perimeter."""
    uca_id = conn.execute(
        text(
            "INSERT INTO structures (code, name, structure_type) "
            "VALUES ('UCA', 'UCA', CAST('universite' AS structure_type)) RETURNING id"
        )
    ).scalar_one()
    conn.execute(
        text("INSERT INTO perimeters (code, name, structure_ids) VALUES ('uca', 'UCA', :ids)"),
        {"ids": [uca_id]},
    )
    conn.execute(
        text("INSERT INTO config (key, value) VALUES ('perimeter_persons', CAST(:v AS jsonb))"),
        {"v": json.dumps("uca")},
    )
    return uca_id


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
    def test_removes_existing(self, sa_sync_conn, sa_repo):
        p = _sa_insert_person(sa_sync_conn)
        sa_sync_conn.execute(
            text(
                "INSERT INTO person_identifiers (person_id, id_type, id_value, source, status) "
                "VALUES (:p, 'orcid', '0000-0001', 'auto', 'pending')"
            ),
            {"p": p},
        )
        remove_identifier(sa_sync_conn, p, "orcid", "0000-0001", repo=sa_repo)
        row = sa_sync_conn.execute(
            text("SELECT id FROM person_identifiers WHERE id_value = '0000-0001'")
        ).first()
        assert row is None

    def test_raises_not_found(self, sa_sync_conn, sa_repo):
        p = _sa_insert_person(sa_sync_conn)
        with pytest.raises(NotFoundError):
            remove_identifier(sa_sync_conn, p, "orcid", "unknown", repo=sa_repo)


class TestUpdateIdentifierStatus:
    def test_sets_status(self, sa_sync_conn, sa_repo):
        p = _sa_insert_person(sa_sync_conn)
        ident_id = sa_sync_conn.execute(
            text(
                "INSERT INTO person_identifiers (person_id, id_type, id_value, source, status) "
                "VALUES (:p, 'orcid', '0000-0001', 'auto', 'pending') RETURNING id"
            ),
            {"p": p},
        ).scalar_one()

        row = update_identifier_status(sa_sync_conn, ident_id, "confirmed", repo=sa_repo)

        assert row["status"] == "confirmed"

    def test_raises_not_found(self, sa_sync_conn, sa_repo):
        with pytest.raises(NotFoundError):
            update_identifier_status(sa_sync_conn, 999999, "confirmed", repo=sa_repo)


class TestReassignIdentifier:
    def test_reassigns(self, sa_sync_conn, sa_repo):
        p1 = _sa_insert_person(sa_sync_conn, "A", "A")
        p2 = _sa_insert_person(sa_sync_conn, "B", "B")
        ident_id = sa_sync_conn.execute(
            text(
                "INSERT INTO person_identifiers (person_id, id_type, id_value, source, status) "
                "VALUES (:p, 'orcid', '0000-0001', 'auto', 'pending') RETURNING id"
            ),
            {"p": p1},
        ).scalar_one()

        reassign_identifier(sa_sync_conn, ident_id, p2, repo=sa_repo)

        row = sa_sync_conn.execute(
            text("SELECT person_id, status::text AS status FROM person_identifiers WHERE id = :i"),
            {"i": ident_id},
        ).one()
        assert row.person_id == p2
        assert row.status == "pending"

    def test_raises_not_found(self, sa_sync_conn, sa_repo):
        p = _sa_insert_person(sa_sync_conn)
        with pytest.raises(NotFoundError):
            reassign_identifier(sa_sync_conn, 999999, p, repo=sa_repo)


class TestSetRejected:
    def test_marks_rejected(self, sa_sync_conn, sa_repo):
        p = _sa_insert_person(sa_sync_conn)
        set_rejected(sa_sync_conn, p, True, repo=sa_repo)
        row = sa_sync_conn.execute(
            text("SELECT rejected FROM persons WHERE id = :p"), {"p": p}
        ).one()
        assert row.rejected is True

    def test_unmarks(self, sa_sync_conn, sa_repo):
        p = _sa_insert_person(sa_sync_conn)
        set_rejected(sa_sync_conn, p, True, repo=sa_repo)
        set_rejected(sa_sync_conn, p, False, repo=sa_repo)
        row = sa_sync_conn.execute(
            text("SELECT rejected FROM persons WHERE id = :p"), {"p": p}
        ).one()
        assert row.rejected is False

    def test_raises_not_found(self, sa_sync_conn, sa_repo):
        with pytest.raises(NotFoundError):
            set_rejected(sa_sync_conn, 999999, True, repo=sa_repo)


class TestUpdateName:
    def test_updates_name_and_refreshes_forms(self, sa_sync_conn, sa_repo):
        p = _sa_insert_person(sa_sync_conn, "Dupont", "Jean")
        # La forme 'dupont jean' doit exister pour vérifier le refresh
        sa_sync_conn.execute(
            text(
                "INSERT INTO person_name_forms (name_form, person_ids, sources) "
                "VALUES ('dupont jean', ARRAY[:p]::integer[], ARRAY['persons']::text[])"
            ),
            {"p": p},
        )
        row = sa_sync_conn.execute(
            text("SELECT id FROM person_name_forms WHERE name_form = 'dupont jean'")
        ).first()
        assert row is not None

        update_name(sa_sync_conn, p, "Martin", "Sophie", repo=sa_repo)

        row = sa_sync_conn.execute(
            text("SELECT last_name, first_name FROM persons WHERE id = :p"), {"p": p}
        ).one()
        assert row.last_name == "Martin"
        assert row.first_name == "Sophie"

        # Nouvelle forme créée
        row = sa_sync_conn.execute(
            text("SELECT id FROM person_name_forms WHERE name_form = 'martin sophie'")
        ).first()
        assert row is not None

    def test_raises_not_found(self, sa_sync_conn, sa_repo):
        with pytest.raises(NotFoundError):
            update_name(sa_sync_conn, 999999, "X", "X", repo=sa_repo)


# ── batch_assign_orphan_authorships ─────────────────────────────────


class TestBatchAssignOrphanAuthorships:
    def test_empty_list_returns_zero(self, sa_sync_conn, sa_repo):
        _sa_setup_uca(sa_sync_conn)
        person_id = _sa_insert_person(sa_sync_conn)
        assert batch_assign_orphan_authorships(sa_sync_conn, person_id, [], repo=sa_repo) == 0

    def test_assigns_and_creates_truth(self, sa_sync_conn, sa_repo):
        _sa_setup_uca(sa_sync_conn)
        person_id = _sa_insert_person(sa_sync_conn)
        pub_id = _sa_insert_publication(sa_sync_conn)
        sp_hal = _sa_insert_source_publication(sa_sync_conn, pub_id, source="hal", source_id="h-1")
        sp_oa = _sa_insert_source_publication(
            sa_sync_conn, pub_id, source="openalex", source_id="W1"
        )
        sp_person_hal = _sa_insert_source_person(sa_sync_conn, source="hal", source_id="hal-p-1")
        sp_person_oa = _sa_insert_source_person(sa_sync_conn, source="openalex", source_id="oa-p-1")
        sa1 = _sa_insert_source_authorship(
            sa_sync_conn, sp_hal, sp_person_hal, source="hal", author_name_normalized="jean dupont"
        )
        sa2 = _sa_insert_source_authorship(
            sa_sync_conn,
            sp_oa,
            sp_person_oa,
            source="openalex",
            author_name_normalized="jean dupont",
        )

        assigned = batch_assign_orphan_authorships(
            sa_sync_conn, person_id, [sa1, sa2], repo=sa_repo
        )

        assert assigned == 2
        # authorship vérité créée pour la publication
        row = sa_sync_conn.execute(
            text("SELECT id FROM authorships WHERE publication_id = :pub AND person_id = :pid"),
            {"pub": pub_id, "pid": person_id},
        ).first()
        assert row is not None
        # FK posée sur les 2 source_authorships
        rows = sa_sync_conn.execute(
            text("SELECT authorship_id FROM source_authorships WHERE id = ANY(:ids)"),
            {"ids": [sa1, sa2]},
        ).all()
        assert all(r.authorship_id is not None for r in rows)

    def test_skips_already_assigned(self, sa_sync_conn, sa_repo):
        _sa_setup_uca(sa_sync_conn)
        p1 = _sa_insert_person(sa_sync_conn, "A", "A")
        p2 = _sa_insert_person(sa_sync_conn, "B", "B")
        pub_id = _sa_insert_publication(sa_sync_conn)
        sp_id = _sa_insert_source_publication(sa_sync_conn, pub_id)
        sp_person = _sa_insert_source_person(sa_sync_conn)
        # sa1 déjà assignée à p1
        sa1 = _sa_insert_source_authorship(sa_sync_conn, sp_id, sp_person, person_id=p1)

        assigned = batch_assign_orphan_authorships(sa_sync_conn, p2, [sa1], repo=sa_repo)

        assert assigned == 0  # pas d'orpheline à rattacher
        row = sa_sync_conn.execute(
            text("SELECT person_id FROM source_authorships WHERE id = :i"), {"i": sa1}
        ).one()
        assert row.person_id == p1  # inchangé


# ── detach_authorships ─────────────────────────────────────────────


class TestDetachAuthorships:
    def test_detaches_and_removes_truth_if_orphan(self, sa_sync_conn, sa_repo, authorship_repo):
        person_id = _sa_insert_person(sa_sync_conn)
        pub_id = _sa_insert_publication(sa_sync_conn)
        sp_id = _sa_insert_source_publication(sa_sync_conn, pub_id)
        sp_person = _sa_insert_source_person(sa_sync_conn)
        auth_id = sa_sync_conn.execute(
            text(
                "INSERT INTO authorships (publication_id, person_id) "
                "VALUES (:pub, :pid) RETURNING id"
            ),
            {"pub": pub_id, "pid": person_id},
        ).scalar_one()
        sa_id = _sa_insert_source_authorship(sa_sync_conn, sp_id, sp_person, person_id=person_id)

        result = detach_authorships(
            sa_sync_conn,
            person_id,
            authorships=[{"source": "hal", "authorship_id": sa_id}],
            repo=sa_repo,
            authorship_repo=authorship_repo,
        )

        assert result["detached"] == 1
        assert result["deleted_authorships"] == 1
        # source_authorship détaché
        row = sa_sync_conn.execute(
            text("SELECT person_id FROM source_authorships WHERE id = :i"), {"i": sa_id}
        ).one()
        assert row.person_id is None
        # authorship vérité supprimée (orpheline)
        row = sa_sync_conn.execute(
            text("SELECT id FROM authorships WHERE id = :i"), {"i": auth_id}
        ).first()
        assert row is None

    def test_cleans_name_form_when_no_remaining(self, sa_sync_conn, sa_repo, authorship_repo):
        person_id = create_person(sa_sync_conn, "Dupont", "Jean", repo=sa_repo)
        # add_name_form simulé via create_person

        # Pas de source_authorship portant "dupont jean" → la forme est nettoyée
        result = detach_authorships(
            sa_sync_conn,
            person_id,
            authorships=[],
            name_form="dupont jean",
            repo=sa_repo,
            authorship_repo=authorship_repo,
        )
        assert result["cleaned_form"] is True

        row = sa_sync_conn.execute(
            text("SELECT person_ids FROM person_name_forms WHERE name_form = 'dupont jean'")
        ).first()
        # La forme a été retirée ou la person_id a été enlevée
        if row:
            assert person_id not in (row.person_ids or [])

    def test_keeps_name_form_if_another_authorship_uses_it(
        self, sa_sync_conn, sa_repo, authorship_repo
    ):
        person_id = create_person(sa_sync_conn, "Dupont", "Jean", repo=sa_repo)
        pub_id = _sa_insert_publication(sa_sync_conn)
        sp_id = _sa_insert_source_publication(sa_sync_conn, pub_id)
        sp_person = _sa_insert_source_person(sa_sync_conn)
        # source_authorship portant la forme "dupont jean"
        _sa_insert_source_authorship(
            sa_sync_conn,
            sp_id,
            sp_person,
            person_id=person_id,
            author_name_normalized="dupont jean",
        )

        result = detach_authorships(
            sa_sync_conn,
            person_id,
            authorships=[],
            name_form="dupont jean",
            repo=sa_repo,
            authorship_repo=authorship_repo,
        )

        assert result["cleaned_form"] is False


class TestMarkDistinctPersons:
    def test_inserts_ordered_pair(self, db, repo):
        p1 = _insert_person(db, "A", "A")
        p2 = _insert_person(db, "B", "B")
        mark_distinct(db, p2, p1, repo=repo)  # ordre inverse
        db.execute(
            "SELECT COUNT(*) AS n FROM distinct_persons "
            "WHERE person_id_a = %s AND person_id_b = %s",
            (min(p1, p2), max(p1, p2)),
        )
        assert db.fetchone()["n"] == 1

    def test_idempotent(self, db, repo):
        p1 = _insert_person(db, "A", "A")
        p2 = _insert_person(db, "B", "B")
        mark_distinct(db, p1, p2, repo=repo)
        mark_distinct(db, p1, p2, repo=repo)  # ON CONFLICT DO NOTHING
        db.execute(
            "SELECT COUNT(*) AS n FROM distinct_persons "
            "WHERE person_id_a = %s AND person_id_b = %s",
            (min(p1, p2), max(p1, p2)),
        )
        assert db.fetchone()["n"] == 1


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
    def test_removes_person_from_form(self, sa_sync_conn, sa_repo):
        p1 = create_person(sa_sync_conn, "Dupont", "Jean", repo=sa_repo)
        p2 = create_person(sa_sync_conn, "Dupont", "Jean", repo=sa_repo)  # même forme 'dupont jean'

        detach_name_form(sa_sync_conn, p1, "dupont jean", repo=sa_repo)

        row = sa_sync_conn.execute(
            text("SELECT person_ids FROM person_name_forms WHERE name_form = 'dupont jean'")
        ).first()
        assert row is not None
        assert p1 not in row.person_ids
        assert p2 in row.person_ids

    def test_deletes_form_when_last_person_detached(self, sa_sync_conn, sa_repo):
        person_id = create_person(sa_sync_conn, "Unique", "Name", repo=sa_repo)

        detach_name_form(sa_sync_conn, person_id, "name unique", repo=sa_repo)

        row = sa_sync_conn.execute(
            text("SELECT id FROM person_name_forms WHERE name_form = 'name unique'")
        ).first()
        assert row is None


# ── assign_orphan_authorship (+ _ensure_truth_authorship) ──────────


class TestAssignOrphanAuthorship:
    def test_raises_on_invalid_source(self, sa_sync_conn, sa_repo):
        with pytest.raises(ValidationError, match="Source inconnue"):
            assign_orphan_authorship(sa_sync_conn, 1, "invalid", 1, repo=sa_repo)

    def test_returns_false_if_already_assigned(self, sa_sync_conn, sa_repo):
        """Si l'authorship a déjà un person_id, l'UPDATE ne matche pas."""
        _sa_setup_uca(sa_sync_conn)
        person_id = _sa_insert_person(sa_sync_conn)
        other_id = _sa_insert_person(sa_sync_conn, "Other", "Author")
        pub_id = _sa_insert_publication(sa_sync_conn)
        sp_id = _sa_insert_source_publication(sa_sync_conn, pub_id)
        sp_person = _sa_insert_source_person(sa_sync_conn)
        sa_id = _sa_insert_source_authorship(sa_sync_conn, sp_id, sp_person, person_id=other_id)

        assert (
            assign_orphan_authorship(sa_sync_conn, person_id, "hal", sa_id, repo=sa_repo) is False
        )

    def test_assigns_and_creates_truth_authorship(self, sa_sync_conn, sa_repo):
        _sa_setup_uca(sa_sync_conn)
        person_id = _sa_insert_person(sa_sync_conn)
        pub_id = _sa_insert_publication(sa_sync_conn)
        sp_id = _sa_insert_source_publication(sa_sync_conn, pub_id)
        sp_person = _sa_insert_source_person(sa_sync_conn)
        sa_id = _sa_insert_source_authorship(sa_sync_conn, sp_id, sp_person)  # orpheline

        result = assign_orphan_authorship(sa_sync_conn, person_id, "hal", sa_id, repo=sa_repo)

        assert result is True
        # person_id assigné sur source_authorship
        row = sa_sync_conn.execute(
            text("SELECT person_id, authorship_id FROM source_authorships WHERE id = :i"),
            {"i": sa_id},
        ).one()
        assert row.person_id == person_id
        assert row.authorship_id is not None

        # authorship vérité créée
        row = sa_sync_conn.execute(
            text("SELECT id FROM authorships WHERE publication_id = :pub AND person_id = :pid"),
            {"pub": pub_id, "pid": person_id},
        ).first()
        assert row is not None

    def test_skips_name_form_if_excluded(self, sa_sync_conn, sa_repo):
        """Si la source authorship est excluded, pas d'ajout de name_form."""
        _sa_setup_uca(sa_sync_conn)
        person_id = _sa_insert_person(sa_sync_conn, "Zzz", "Zzz")  # forme 'zzz' / 'zzz zzz'
        pub_id = _sa_insert_publication(sa_sync_conn)
        sp_id = _sa_insert_source_publication(sa_sync_conn, pub_id)
        sp_person = _sa_insert_source_person(sa_sync_conn)
        sa_id = _sa_insert_source_authorship(
            sa_sync_conn,
            sp_id,
            sp_person,
            author_name_normalized="other name",
            excluded=True,
        )

        assign_orphan_authorship(sa_sync_conn, person_id, "hal", sa_id, repo=sa_repo)

        # Aucune nouvelle name_form 'other name' n'a été créée
        row = sa_sync_conn.execute(
            text("SELECT id FROM person_name_forms WHERE name_form = 'other name'")
        ).first()
        assert row is None
