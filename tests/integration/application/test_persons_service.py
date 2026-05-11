"""Tests de caractérisation pour application/persons.py et
application/authorships/assign_orphans.py.

Couvre link/unlink_authorship (branches source invalide), add_identifier,
detach_name_form, assign_orphan_authorship (qui couvre la
re-synchronisation de l'authorship canonique depuis ses sources),
merge_person, etc.
"""

import json

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.authorships.assign_orphans import (
    assign_orphan_authorship,
    batch_assign_orphan_authorships,
)
from application.persons import (
    add_identifier,
    add_identifiers_from_authorships,
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
def repo(sa_sync_conn):
    return person_repository(sa_sync_conn)


@pytest.fixture
def authorship_repo(sa_sync_conn):
    return authorship_repository(sa_sync_conn)


# ── Helpers ─────────────────────────────────────────────────


def _insert_person(conn, last="Dupont", first="Jean"):
    return conn.execute(
        text(
            "INSERT INTO persons (last_name, first_name, "
            "                     last_name_normalized, first_name_normalized) "
            "VALUES (:l, :f, lower(:l), lower(:f)) RETURNING id"
        ),
        {"l": last, "f": first},
    ).scalar_one()


def _insert_publication(conn, title="Test"):
    return conn.execute(
        text("INSERT INTO publications (title, pub_year) VALUES (:t, 2024) RETURNING id"),
        {"t": title},
    ).scalar_one()


def _insert_source_publication(conn, publication_id, source="hal", source_id="hal-1"):
    return conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, publication_id) "
            "VALUES (:s, :sid, 'Test', :pid) RETURNING id"
        ),
        {"s": source, "sid": source_id, "pid": publication_id},
    ).scalar_one()


_INSERT_SOURCE_PERSON_SQL = text(
    "INSERT INTO source_persons (source, source_id, full_name, source_ids) "
    "VALUES (:s, :sid, :n, :si) RETURNING id"
).bindparams(bindparam("si", type_=JSONB))


def _insert_source_person(
    conn, source="hal", source_id="hal-p-1", full_name="Jean Dupont", source_ids=None
):
    return conn.execute(
        _INSERT_SOURCE_PERSON_SQL,
        {"s": source, "sid": source_id, "n": full_name, "si": source_ids},
    ).scalar_one()


def _insert_source_authorship(
    conn,
    source_publication_id,
    source_person_id,
    source="hal",
    person_id=None,
    author_name_normalized="jean dupont",
    excluded=False,
):
    return conn.execute(
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
    ).scalar_one()


def _setup_uca(conn):
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


def _scalar(conn, sql_text: str, **params):
    return conn.execute(text(sql_text), params).scalar_one_or_none()


# ── link_authorship / unlink_authorship ────────────────────────────


class TestLinkAuthorship:
    def test_ignores_invalid_source(self, sa_sync_conn, repo):
        """Source inconnue → no-op silencieux (pas d'exception)."""
        link_authorship(sa_sync_conn, 1, "invalid", 1, repo=repo)

    def test_sets_person_id_on_source_authorship(self, sa_sync_conn, repo):
        person_id = _insert_person(sa_sync_conn)
        pub_id = _insert_publication(sa_sync_conn)
        sp_id = _insert_source_publication(sa_sync_conn, pub_id)
        sp_person = _insert_source_person(sa_sync_conn)
        sa_id = _insert_source_authorship(sa_sync_conn, sp_id, sp_person)

        link_authorship(sa_sync_conn, person_id, "hal", sa_id, repo=repo)

        assert (
            _scalar(sa_sync_conn, "SELECT person_id FROM source_authorships WHERE id = :i", i=sa_id)
            == person_id
        )

    def test_dual_write_hal_person(self, sa_sync_conn, repo):
        """Pour HAL avec hal_person_id, propage aussi à source_persons."""
        person_id = _insert_person(sa_sync_conn)
        pub_id = _insert_publication(sa_sync_conn)
        sp_id = _insert_source_publication(sa_sync_conn, pub_id)
        sp_person = _insert_source_person(sa_sync_conn, source_ids={"hal_person_id": 42})
        sa_id = _insert_source_authorship(sa_sync_conn, sp_id, sp_person)

        link_authorship(
            sa_sync_conn,
            person_id,
            "hal",
            sa_id,
            source_person_id=sp_person,
            has_hal_person_id=True,
            repo=repo,
        )

        assert (
            _scalar(sa_sync_conn, "SELECT person_id FROM source_persons WHERE id = :i", i=sp_person)
            == person_id
        )


class TestUnlinkAuthorship:
    def test_ignores_invalid_source(self, sa_sync_conn, repo):
        unlink_authorship(sa_sync_conn, 1, "invalid", 1, repo=repo)

    def test_unsets_person_id(self, sa_sync_conn, repo):
        person_id = _insert_person(sa_sync_conn)
        pub_id = _insert_publication(sa_sync_conn)
        sp_id = _insert_source_publication(sa_sync_conn, pub_id)
        sp_person = _insert_source_person(sa_sync_conn)
        sa_id = _insert_source_authorship(sa_sync_conn, sp_id, sp_person, person_id=person_id)

        unlink_authorship(sa_sync_conn, person_id, "hal", sa_id, repo=repo)

        assert (
            _scalar(sa_sync_conn, "SELECT person_id FROM source_authorships WHERE id = :i", i=sa_id)
            is None
        )

    def test_noop_if_person_id_mismatch(self, sa_sync_conn, repo):
        """Ne détache pas si l'authorship est liée à une autre personne."""
        p1 = _insert_person(sa_sync_conn, "Dupont", "Jean")
        p2 = _insert_person(sa_sync_conn, "Martin", "Sophie")
        pub_id = _insert_publication(sa_sync_conn)
        sp_id = _insert_source_publication(sa_sync_conn, pub_id)
        sp_person = _insert_source_person(sa_sync_conn)
        sa_id = _insert_source_authorship(sa_sync_conn, sp_id, sp_person, person_id=p1)

        unlink_authorship(sa_sync_conn, p2, "hal", sa_id, repo=repo)

        assert (
            _scalar(sa_sync_conn, "SELECT person_id FROM source_authorships WHERE id = :i", i=sa_id)
            == p1
        )


# ── add_identifier ─────────────────────────────────────────────────


class TestAddIdentifier:
    def test_inserts_new(self, sa_sync_conn, repo):
        person_id = _insert_person(sa_sync_conn)
        add_identifier(sa_sync_conn, person_id, "orcid", "0000-0001-2345-6789", repo=repo)
        status = _scalar(
            sa_sync_conn,
            "SELECT status FROM person_identifiers WHERE id_type='orcid' AND id_value=:v",
            v="0000-0001-2345-6789",
        )
        assert status == "pending"

    def test_reassigns_if_rejected(self, sa_sync_conn, repo):
        p1 = _insert_person(sa_sync_conn, "A", "A")
        p2 = _insert_person(sa_sync_conn, "B", "B")
        add_identifier(sa_sync_conn, p1, "orcid", "0000-0001", repo=repo)
        sa_sync_conn.execute(
            text("UPDATE person_identifiers SET status='rejected' WHERE id_value='0000-0001'")
        )
        add_identifier(sa_sync_conn, p2, "orcid", "0000-0001", repo=repo)

        row = sa_sync_conn.execute(
            text("SELECT person_id, status FROM person_identifiers WHERE id_value='0000-0001'")
        ).one()
        assert row.person_id == p2
        assert row.status == "pending"

    def test_does_not_override_pending(self, sa_sync_conn, repo):
        """Si le même identifiant existe en 'pending', on ne touche pas."""
        p1 = _insert_person(sa_sync_conn, "A", "A")
        p2 = _insert_person(sa_sync_conn, "B", "B")
        add_identifier(sa_sync_conn, p1, "orcid", "0000-0001", repo=repo)
        add_identifier(sa_sync_conn, p2, "orcid", "0000-0001", repo=repo)

        assert (
            _scalar(
                sa_sync_conn,
                "SELECT person_id FROM person_identifiers WHERE id_value='0000-0001'",
            )
            == p1
        )

    def test_idhal_attaches_hal_source_person(self, sa_sync_conn, repo):
        """Ajouter un idhal à une personne rattache le compte HAL correspondant."""
        person_id = _insert_person(sa_sync_conn)
        sp = _insert_source_person(sa_sync_conn, source_ids={"idhal": "jean-dupont"})

        add_identifier(sa_sync_conn, person_id, "idhal", "jean-dupont", repo=repo)

        assert (
            _scalar(sa_sync_conn, "SELECT person_id FROM source_persons WHERE id = :i", i=sp)
            == person_id
        )


class TestRemoveIdentifier:
    def test_removes_existing(self, sa_sync_conn, repo):
        p = _insert_person(sa_sync_conn)
        sa_sync_conn.execute(
            text(
                "INSERT INTO person_identifiers (person_id, id_type, id_value, source, status) "
                "VALUES (:p, 'orcid', '0000-0001', 'auto', 'pending')"
            ),
            {"p": p},
        )
        remove_identifier(sa_sync_conn, p, "orcid", "0000-0001", repo=repo)
        row = sa_sync_conn.execute(
            text("SELECT id FROM person_identifiers WHERE id_value = '0000-0001'")
        ).first()
        assert row is None

    def test_raises_not_found(self, sa_sync_conn, repo):
        p = _insert_person(sa_sync_conn)
        with pytest.raises(NotFoundError):
            remove_identifier(sa_sync_conn, p, "orcid", "unknown", repo=repo)


class TestUpdateIdentifierStatus:
    def test_sets_status(self, sa_sync_conn, repo):
        p = _insert_person(sa_sync_conn)
        ident_id = sa_sync_conn.execute(
            text(
                "INSERT INTO person_identifiers (person_id, id_type, id_value, source, status) "
                "VALUES (:p, 'orcid', '0000-0001', 'auto', 'pending') RETURNING id"
            ),
            {"p": p},
        ).scalar_one()

        row = update_identifier_status(sa_sync_conn, ident_id, "confirmed", repo=repo)

        assert row["status"] == "confirmed"

    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            update_identifier_status(sa_sync_conn, 999999, "confirmed", repo=repo)


class TestReassignIdentifier:
    def test_reassigns(self, sa_sync_conn, repo):
        p1 = _insert_person(sa_sync_conn, "A", "A")
        p2 = _insert_person(sa_sync_conn, "B", "B")
        ident_id = sa_sync_conn.execute(
            text(
                "INSERT INTO person_identifiers (person_id, id_type, id_value, source, status) "
                "VALUES (:p, 'orcid', '0000-0001', 'auto', 'pending') RETURNING id"
            ),
            {"p": p1},
        ).scalar_one()

        reassign_identifier(sa_sync_conn, ident_id, p2, repo=repo)

        row = sa_sync_conn.execute(
            text("SELECT person_id, status::text AS status FROM person_identifiers WHERE id = :i"),
            {"i": ident_id},
        ).one()
        assert row.person_id == p2
        assert row.status == "pending"

    def test_raises_not_found(self, sa_sync_conn, repo):
        p = _insert_person(sa_sync_conn)
        with pytest.raises(NotFoundError):
            reassign_identifier(sa_sync_conn, 999999, p, repo=repo)


class TestSetRejected:
    def test_marks_rejected(self, sa_sync_conn, repo):
        p = _insert_person(sa_sync_conn)
        set_rejected(sa_sync_conn, p, True, repo=repo)
        assert _scalar(sa_sync_conn, "SELECT rejected FROM persons WHERE id = :p", p=p) is True

    def test_unmarks(self, sa_sync_conn, repo):
        p = _insert_person(sa_sync_conn)
        set_rejected(sa_sync_conn, p, True, repo=repo)
        set_rejected(sa_sync_conn, p, False, repo=repo)
        assert _scalar(sa_sync_conn, "SELECT rejected FROM persons WHERE id = :p", p=p) is False

    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            set_rejected(sa_sync_conn, 999999, True, repo=repo)


class TestUpdateName:
    def test_updates_name_and_refreshes_forms(self, sa_sync_conn, repo):
        p = _insert_person(sa_sync_conn, "Dupont", "Jean")
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

        update_name(sa_sync_conn, p, "Martin", "Sophie", repo=repo)

        row = sa_sync_conn.execute(
            text("SELECT last_name, first_name FROM persons WHERE id = :p"), {"p": p}
        ).one()
        assert row.last_name == "Martin"
        assert row.first_name == "Sophie"

        row = sa_sync_conn.execute(
            text("SELECT id FROM person_name_forms WHERE name_form = 'martin sophie'")
        ).first()
        assert row is not None

    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            update_name(sa_sync_conn, 999999, "X", "X", repo=repo)


# ── batch_assign_orphan_authorships ─────────────────────────────────


class TestBatchAssignOrphanAuthorships:
    def test_empty_list_returns_zero(self, sa_sync_conn, repo):
        _setup_uca(sa_sync_conn)
        person_id = _insert_person(sa_sync_conn)
        assert batch_assign_orphan_authorships(sa_sync_conn, person_id, [], repo=repo) == 0

    def test_assigns_and_creates_authorship(self, sa_sync_conn, repo):
        _setup_uca(sa_sync_conn)
        person_id = _insert_person(sa_sync_conn)
        pub_id = _insert_publication(sa_sync_conn)
        sp_hal = _insert_source_publication(sa_sync_conn, pub_id, source="hal", source_id="h-1")
        sp_oa = _insert_source_publication(sa_sync_conn, pub_id, source="openalex", source_id="W1")
        sp_person_hal = _insert_source_person(sa_sync_conn, source="hal", source_id="hal-p-1")
        sp_person_oa = _insert_source_person(sa_sync_conn, source="openalex", source_id="oa-p-1")
        sa1 = _insert_source_authorship(
            sa_sync_conn, sp_hal, sp_person_hal, source="hal", author_name_normalized="jean dupont"
        )
        sa2 = _insert_source_authorship(
            sa_sync_conn,
            sp_oa,
            sp_person_oa,
            source="openalex",
            author_name_normalized="jean dupont",
        )

        assigned = batch_assign_orphan_authorships(sa_sync_conn, person_id, [sa1, sa2], repo=repo)

        assert assigned == 2
        row = sa_sync_conn.execute(
            text("SELECT id FROM authorships WHERE publication_id = :pub AND person_id = :pid"),
            {"pub": pub_id, "pid": person_id},
        ).first()
        assert row is not None
        rows = sa_sync_conn.execute(
            text("SELECT authorship_id FROM source_authorships WHERE id = ANY(:ids)"),
            {"ids": [sa1, sa2]},
        ).all()
        assert all(r.authorship_id is not None for r in rows)

    def test_skips_already_assigned(self, sa_sync_conn, repo):
        _setup_uca(sa_sync_conn)
        p1 = _insert_person(sa_sync_conn, "A", "A")
        p2 = _insert_person(sa_sync_conn, "B", "B")
        pub_id = _insert_publication(sa_sync_conn)
        sp_id = _insert_source_publication(sa_sync_conn, pub_id)
        sp_person = _insert_source_person(sa_sync_conn)
        sa1 = _insert_source_authorship(sa_sync_conn, sp_id, sp_person, person_id=p1)

        assigned = batch_assign_orphan_authorships(sa_sync_conn, p2, [sa1], repo=repo)

        assert assigned == 0
        assert (
            _scalar(sa_sync_conn, "SELECT person_id FROM source_authorships WHERE id = :i", i=sa1)
            == p1
        )


# ── detach_authorships ─────────────────────────────────────────────


class TestDetachAuthorships:
    def test_detaches_and_removes_authorship_if_orphan(self, sa_sync_conn, repo, authorship_repo):
        person_id = _insert_person(sa_sync_conn)
        pub_id = _insert_publication(sa_sync_conn)
        sp_id = _insert_source_publication(sa_sync_conn, pub_id)
        sp_person = _insert_source_person(sa_sync_conn)
        auth_id = sa_sync_conn.execute(
            text(
                "INSERT INTO authorships (publication_id, person_id) "
                "VALUES (:pub, :pid) RETURNING id"
            ),
            {"pub": pub_id, "pid": person_id},
        ).scalar_one()
        sa_id = _insert_source_authorship(sa_sync_conn, sp_id, sp_person, person_id=person_id)

        result = detach_authorships(
            sa_sync_conn,
            person_id,
            authorships=[{"source": "hal", "authorship_id": sa_id}],
            repo=repo,
            authorship_repo=authorship_repo,
        )

        assert result["detached"] == 1
        assert result["deleted_authorships"] == 1
        assert (
            _scalar(sa_sync_conn, "SELECT person_id FROM source_authorships WHERE id = :i", i=sa_id)
            is None
        )
        row = sa_sync_conn.execute(
            text("SELECT id FROM authorships WHERE id = :i"), {"i": auth_id}
        ).first()
        assert row is None

    def test_cleans_name_form_when_no_remaining(self, sa_sync_conn, repo, authorship_repo):
        person_id = create_person(sa_sync_conn, "Dupont", "Jean", repo=repo)

        result = detach_authorships(
            sa_sync_conn,
            person_id,
            authorships=[],
            name_form="dupont jean",
            repo=repo,
            authorship_repo=authorship_repo,
        )
        assert result["cleaned_form"] is True

        row = sa_sync_conn.execute(
            text("SELECT person_ids FROM person_name_forms WHERE name_form = 'dupont jean'")
        ).first()
        if row:
            assert person_id not in (row.person_ids or [])

    def test_keeps_name_form_if_another_authorship_uses_it(
        self, sa_sync_conn, repo, authorship_repo
    ):
        person_id = create_person(sa_sync_conn, "Dupont", "Jean", repo=repo)
        pub_id = _insert_publication(sa_sync_conn)
        sp_id = _insert_source_publication(sa_sync_conn, pub_id)
        sp_person = _insert_source_person(sa_sync_conn)
        _insert_source_authorship(
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
            repo=repo,
            authorship_repo=authorship_repo,
        )

        assert result["cleaned_form"] is False


class TestMarkDistinctPersons:
    def test_inserts_ordered_pair(self, sa_sync_conn, repo):
        p1 = _insert_person(sa_sync_conn, "A", "A")
        p2 = _insert_person(sa_sync_conn, "B", "B")
        mark_distinct(sa_sync_conn, p2, p1, repo=repo)
        n = sa_sync_conn.execute(
            text(
                "SELECT COUNT(*) AS n FROM distinct_persons "
                "WHERE person_id_a = :a AND person_id_b = :b"
            ),
            {"a": min(p1, p2), "b": max(p1, p2)},
        ).scalar_one()
        assert n == 1

    def test_idempotent(self, sa_sync_conn, repo):
        p1 = _insert_person(sa_sync_conn, "A", "A")
        p2 = _insert_person(sa_sync_conn, "B", "B")
        mark_distinct(sa_sync_conn, p1, p2, repo=repo)
        mark_distinct(sa_sync_conn, p1, p2, repo=repo)
        n = sa_sync_conn.execute(
            text(
                "SELECT COUNT(*) AS n FROM distinct_persons "
                "WHERE person_id_a = :a AND person_id_b = :b"
            ),
            {"a": min(p1, p2), "b": max(p1, p2)},
        ).scalar_one()
        assert n == 1


class TestAddIdentifiersFromAuthorships:
    def test_adds_orcid_idhal_idref_once(self, sa_sync_conn, repo):
        person_id = _insert_person(sa_sync_conn)
        authorships = [
            {"source": "hal", "orcid": "0000-0001", "idhal": "jdupont"},
            {"source": "scanr", "orcid": "0000-0001", "idref": "123456"},
        ]
        add_identifiers_from_authorships(sa_sync_conn, person_id, authorships, repo=repo)

        rows = sa_sync_conn.execute(
            text(
                "SELECT id_type, id_value, source FROM person_identifiers "
                "WHERE person_id = :pid ORDER BY id_type"
            ),
            {"pid": person_id},
        ).all()
        id_types = [r.id_type for r in rows]
        assert id_types == ["idhal", "idref", "orcid"]


# ── detach_name_form ───────────────────────────────────────────────


class TestDetachNameForm:
    def test_removes_person_from_form(self, sa_sync_conn, repo):
        p1 = create_person(sa_sync_conn, "Dupont", "Jean", repo=repo)
        p2 = create_person(sa_sync_conn, "Dupont", "Jean", repo=repo)

        detach_name_form(sa_sync_conn, p1, "dupont jean", repo=repo)

        row = sa_sync_conn.execute(
            text("SELECT person_ids FROM person_name_forms WHERE name_form = 'dupont jean'")
        ).first()
        assert row is not None
        assert p1 not in row.person_ids
        assert p2 in row.person_ids

    def test_deletes_form_when_last_person_detached(self, sa_sync_conn, repo):
        person_id = create_person(sa_sync_conn, "Unique", "Name", repo=repo)

        detach_name_form(sa_sync_conn, person_id, "name unique", repo=repo)

        row = sa_sync_conn.execute(
            text("SELECT id FROM person_name_forms WHERE name_form = 'name unique'")
        ).first()
        assert row is None


# ── assign_orphan_authorship ───────────────────────────────────────


class TestAssignOrphanAuthorship:
    def test_raises_on_invalid_source(self, sa_sync_conn, repo):
        with pytest.raises(ValidationError, match="Source inconnue"):
            assign_orphan_authorship(sa_sync_conn, 1, "invalid", 1, repo=repo)

    def test_returns_false_if_already_assigned(self, sa_sync_conn, repo):
        """Si l'authorship a déjà un person_id, l'UPDATE ne matche pas."""
        _setup_uca(sa_sync_conn)
        person_id = _insert_person(sa_sync_conn)
        other_id = _insert_person(sa_sync_conn, "Other", "Author")
        pub_id = _insert_publication(sa_sync_conn)
        sp_id = _insert_source_publication(sa_sync_conn, pub_id)
        sp_person = _insert_source_person(sa_sync_conn)
        sa_id = _insert_source_authorship(sa_sync_conn, sp_id, sp_person, person_id=other_id)

        assert assign_orphan_authorship(sa_sync_conn, person_id, "hal", sa_id, repo=repo) is False

    def test_assigns_and_creates_authorship(self, sa_sync_conn, repo):
        _setup_uca(sa_sync_conn)
        person_id = _insert_person(sa_sync_conn)
        pub_id = _insert_publication(sa_sync_conn)
        sp_id = _insert_source_publication(sa_sync_conn, pub_id)
        sp_person = _insert_source_person(sa_sync_conn)
        sa_id = _insert_source_authorship(sa_sync_conn, sp_id, sp_person)

        result = assign_orphan_authorship(sa_sync_conn, person_id, "hal", sa_id, repo=repo)

        assert result is True
        row = sa_sync_conn.execute(
            text("SELECT person_id, authorship_id FROM source_authorships WHERE id = :i"),
            {"i": sa_id},
        ).one()
        assert row.person_id == person_id
        assert row.authorship_id is not None

        row = sa_sync_conn.execute(
            text("SELECT id FROM authorships WHERE publication_id = :pub AND person_id = :pid"),
            {"pub": pub_id, "pid": person_id},
        ).first()
        assert row is not None

    def test_skips_name_form_if_excluded(self, sa_sync_conn, repo):
        """Si la source authorship est excluded, pas d'ajout de name_form."""
        _setup_uca(sa_sync_conn)
        person_id = _insert_person(sa_sync_conn, "Zzz", "Zzz")
        pub_id = _insert_publication(sa_sync_conn)
        sp_id = _insert_source_publication(sa_sync_conn, pub_id)
        sp_person = _insert_source_person(sa_sync_conn)
        sa_id = _insert_source_authorship(
            sa_sync_conn,
            sp_id,
            sp_person,
            author_name_normalized="other name",
            excluded=True,
        )

        assign_orphan_authorship(sa_sync_conn, person_id, "hal", sa_id, repo=repo)

        row = sa_sync_conn.execute(
            text("SELECT id FROM person_name_forms WHERE name_form = 'other name'")
        ).first()
        assert row is None
