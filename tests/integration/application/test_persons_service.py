"""Tests de caractérisation pour application/persons/core.py et
application/authorships/assign_orphans.py.

Couvre link/unlink_authorship (branches source invalide), add_identifier,
update_name_form_status, assign_orphan_authorship (qui couvre la
re-synchronisation de l'authorship canonique depuis ses sources),
merge_person, etc.
"""

import json

import pytest
from sqlalchemy import text

from application.services.authorships.assign_orphans import (
    assign_orphan_authorship,
    batch_assign_orphan_authorships,
)
from application.services.persons.core import (
    AddIdentifierOutcome,
    add_identifier,
    add_identifiers_from_authorships,
    create_person,
    detach_authorships,
    link_authorship,
    mark_distinct,
    merge_person,
    reassign_identifier,
    remove_identifier,
    set_rejected,
    unlink_authorship,
    update_identifier_status,
    update_name,
    update_name_form_status,
)
from domain.errors import (
    AuthorshipAlreadyAssignedError,
    NotFoundError,
    RejectedPairError,
    ValidationError,
)
from infrastructure.repositories import (
    authorship_repository,
    person_repository,
)
from tests.integration.helpers.authorships import upsert_identity


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


def _insert_source_authorship(
    conn,
    source_publication_id,
    *,
    source="hal",
    author_position=0,
    person_id=None,
    author_name_normalized="jean dupont",
):
    identity_id = upsert_identity(conn, author_name_normalized=author_name_normalized)
    return conn.execute(
        text(
            "INSERT INTO source_authorships (source, source_publication_id, "
            "                                author_position, person_id, identity_id) "
            "VALUES (:s, :spid, :pos, :pid, :iid) RETURNING id"
        ),
        {
            "s": source,
            "spid": source_publication_id,
            "pos": author_position,
            "pid": person_id,
            "iid": identity_id,
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
    def test_rejects_unknown_source(self, sa_sync_conn, repo):
        """Source hors registre → `ValidationError` (mappée en 400 côté API)."""
        with pytest.raises(ValidationError):
            link_authorship(1, "invalid", 1, repo=repo, resolution_mode="name")

    def test_sets_person_id_on_source_authorship(self, sa_sync_conn, repo):
        person_id = _insert_person(sa_sync_conn)
        pub_id = _insert_publication(sa_sync_conn)
        sp_id = _insert_source_publication(sa_sync_conn, pub_id)
        sa_id = _insert_source_authorship(sa_sync_conn, sp_id)

        link_authorship(person_id, "hal", sa_id, repo=repo, resolution_mode="name")

        assert (
            _scalar(sa_sync_conn, "SELECT person_id FROM source_authorships WHERE id = :i", i=sa_id)
            == person_id
        )
        assert (
            _scalar(
                sa_sync_conn,
                "SELECT resolution_mode FROM source_authorships WHERE id = :i",
                i=sa_id,
            )
            == "name"
        )


class TestUnlinkAuthorship:
    def test_rejects_unknown_source(self, sa_sync_conn, repo):
        with pytest.raises(ValidationError):
            unlink_authorship(1, "invalid", 1, repo=repo)

    def test_unsets_person_id(self, sa_sync_conn, repo):
        person_id = _insert_person(sa_sync_conn)
        pub_id = _insert_publication(sa_sync_conn)
        sp_id = _insert_source_publication(sa_sync_conn, pub_id)
        sa_id = _insert_source_authorship(sa_sync_conn, sp_id, person_id=person_id)

        unlink_authorship(person_id, "hal", sa_id, repo=repo)

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
        sa_id = _insert_source_authorship(sa_sync_conn, sp_id, person_id=p1)

        unlink_authorship(p2, "hal", sa_id, repo=repo)

        assert (
            _scalar(sa_sync_conn, "SELECT person_id FROM source_authorships WHERE id = :i", i=sa_id)
            == p1
        )


# ── add_identifier ─────────────────────────────────────────────────


class TestAddIdentifier:
    def test_inserts_new(self, sa_sync_conn, repo):
        person_id = _insert_person(sa_sync_conn)
        result = add_identifier(person_id, "orcid", "0000-0001-2345-6789", repo=repo)
        assert result.outcome is AddIdentifierOutcome.ADDED
        assert result.id_value == "0000-0001-2345-6789"
        status = _scalar(
            sa_sync_conn,
            "SELECT status FROM person_identifiers WHERE id_type='orcid' AND id_value=:v",
            v="0000-0001-2345-6789",
        )
        assert status == "pending"

    def test_reassigns_if_rejected(self, sa_sync_conn, repo):
        p1 = _insert_person(sa_sync_conn, "A", "A")
        p2 = _insert_person(sa_sync_conn, "B", "B")
        add_identifier(p1, "orcid", "0000-0001-2345-6789", repo=repo)
        sa_sync_conn.execute(
            text(
                "UPDATE person_identifiers SET status='rejected' "
                "WHERE id_value='0000-0001-2345-6789'"
            )
        )
        result = add_identifier(p2, "orcid", "0000-0001-2345-6789", repo=repo)
        assert result.outcome is AddIdentifierOutcome.REASSIGNED

        row = sa_sync_conn.execute(
            text(
                "SELECT person_id, status FROM person_identifiers "
                "WHERE id_value='0000-0001-2345-6789'"
            )
        ).one()
        assert row.person_id == p2
        assert row.status == "pending"

    def test_raises_when_pending_on_other_person(self, sa_sync_conn, repo):
        """Si le même identifiant existe en 'pending' sur une autre personne,
        on lève `CannotAttributeConflict` (pour réattribuer, il faut d'abord
        passer le statut à 'rejected')."""
        import pytest

        from domain.errors import CannotAttributeConflict

        p1 = _insert_person(sa_sync_conn, "A", "A")
        p2 = _insert_person(sa_sync_conn, "B", "B")
        add_identifier(p1, "orcid", "0000-0001-2345-6789", repo=repo)

        with pytest.raises(CannotAttributeConflict):
            add_identifier(p2, "orcid", "0000-0001-2345-6789", repo=repo)

        # L'identifiant reste rattaché à p1.
        assert (
            _scalar(
                sa_sync_conn,
                "SELECT person_id FROM person_identifiers WHERE id_value='0000-0001-2345-6789'",
            )
            == p1
        )

    def test_idempotent_on_same_person(self, sa_sync_conn, repo):
        """Réappliquer add_identifier sur la même personne ne change rien."""
        p = _insert_person(sa_sync_conn)
        add_identifier(p, "orcid", "0000-0001-2345-6789", repo=repo)
        result = add_identifier(p, "orcid", "0000-0001-2345-6789", repo=repo)  # no-op
        assert result.outcome is AddIdentifierOutcome.ALREADY_EXISTS

        row = sa_sync_conn.execute(
            text(
                "SELECT person_id, status FROM person_identifiers "
                "WHERE id_value='0000-0001-2345-6789'"
            )
        ).one()
        assert row.person_id == p
        assert row.status == "pending"


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
        remove_identifier(p, "orcid", "0000-0001", repo=repo)
        row = sa_sync_conn.execute(
            text("SELECT id FROM person_identifiers WHERE id_value = '0000-0001'")
        ).first()
        assert row is None

    def test_raises_not_found(self, sa_sync_conn, repo):
        p = _insert_person(sa_sync_conn)
        with pytest.raises(NotFoundError):
            remove_identifier(p, "orcid", "unknown", repo=repo)


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

        row = update_identifier_status(ident_id, "confirmed", repo=repo)

        assert row["status"] == "confirmed"

    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            update_identifier_status(999999, "confirmed", repo=repo)


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

        reassign_identifier(ident_id, p2, repo=repo)

        row = sa_sync_conn.execute(
            text("SELECT person_id, status::text AS status FROM person_identifiers WHERE id = :i"),
            {"i": ident_id},
        ).one()
        assert row.person_id == p2
        assert row.status == "pending"

    def test_raises_not_found(self, sa_sync_conn, repo):
        p = _insert_person(sa_sync_conn)
        with pytest.raises(NotFoundError):
            reassign_identifier(999999, p, repo=repo)


class TestSetRejected:
    def test_marks_rejected(self, sa_sync_conn, repo):
        p = _insert_person(sa_sync_conn)
        set_rejected(p, True, repo=repo)
        assert _scalar(sa_sync_conn, "SELECT rejected FROM persons WHERE id = :p", p=p) is True

    def test_unmarks(self, sa_sync_conn, repo):
        p = _insert_person(sa_sync_conn)
        set_rejected(p, True, repo=repo)
        set_rejected(p, False, repo=repo)
        assert _scalar(sa_sync_conn, "SELECT rejected FROM persons WHERE id = :p", p=p) is False

    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            set_rejected(999999, True, repo=repo)


class TestUpdateName:
    def test_updates_name_and_refreshes_forms(self, sa_sync_conn, repo):
        p = _insert_person(sa_sync_conn, "Dupont", "Jean")
        sa_sync_conn.execute(
            text(
                "INSERT INTO person_name_forms (name_form, person_id, sources) "
                "VALUES ('dupont jean', :pid, ARRAY['persons'])"
            ),
            {"pid": p},
        )

        update_name(p, "Martin", "Sophie", repo=repo)

        row = sa_sync_conn.execute(
            text("SELECT last_name, first_name FROM persons WHERE id = :p"), {"p": p}
        ).one()
        assert row.last_name == "Martin"
        assert row.first_name == "Sophie"

        row = sa_sync_conn.execute(
            text(
                "SELECT sources FROM person_name_forms "
                "WHERE name_form = 'martin sophie' AND person_id = :pid"
            ),
            {"pid": p},
        ).one()
        assert row.sources == ["persons"]

        # L'ancienne forme 'dupont jean' n'avait que la source 'persons'
        # pour ce pid : refresh_name_forms a dû supprimer la row entièrement.
        row = sa_sync_conn.execute(
            text(
                "SELECT 1 FROM person_name_forms "
                "WHERE name_form = 'dupont jean' AND person_id = :pid"
            ),
            {"pid": p},
        ).first()
        assert row is None

    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            update_name(999999, "X", "X", repo=repo)

    def test_strips_surrounding_space(self, sa_sync_conn, repo):
        p = _insert_person(sa_sync_conn, "Dupont", "Jean")
        update_name(p, "  Martin  ", "  Sophie  ", repo=repo)
        row = sa_sync_conn.execute(
            text("SELECT last_name, first_name FROM persons WHERE id = :p"), {"p": p}
        ).one()
        assert row.last_name == "Martin"
        assert row.first_name == "Sophie"

    def test_raises_without_last_name(self, sa_sync_conn, repo):
        """Effacer le patronyme retirerait à la personne les formes que seul son nom canonique porte."""
        p = _insert_person(sa_sync_conn, "Dupont", "Jean")
        with pytest.raises(ValidationError, match="nom est requis"):
            update_name(p, "", "Jean", repo=repo)

    def test_raises_on_blank_last_name(self, sa_sync_conn, repo):
        p = _insert_person(sa_sync_conn, "Dupont", "Jean")
        with pytest.raises(ValidationError, match="nom est requis"):
            update_name(p, "   ", "Jean", repo=repo)


# ── create_person ───────────────────────────────────────────────────


class TestCreatePerson:
    def test_creates_and_computes_name_forms(self, sa_sync_conn, repo):
        p = create_person("Dupont", "Jean", repo=repo)
        forms = {
            r.name_form
            for r in sa_sync_conn.execute(
                text("SELECT name_form FROM person_name_forms WHERE person_id = :p"), {"p": p}
            )
        }
        assert "dupont jean" in forms

    def test_strips_surrounding_space(self, sa_sync_conn, repo):
        p = create_person("  Dupont  ", "  Jean  ", repo=repo)
        row = sa_sync_conn.execute(
            text("SELECT last_name, first_name FROM persons WHERE id = :p"), {"p": p}
        ).one()
        assert row.last_name == "Dupont"
        assert row.first_name == "Jean"

    def test_raises_without_last_name(self, sa_sync_conn, repo):
        """Sans patronyme, `compute_person_name_forms` ne rend aucune forme : la personne ne serait atteignable par aucun nom."""
        with pytest.raises(ValidationError, match="nom est requis"):
            create_person("", "Jean", repo=repo)


# ── merge_person ────────────────────────────────────────────────────


class TestMergePerson:
    def test_raises_on_self_merge(self, sa_sync_conn, repo):
        p = _insert_person(sa_sync_conn)
        with pytest.raises(ValidationError, match="elle-même"):
            merge_person(p, p, repo=repo)

    def test_raises_not_found(self, sa_sync_conn, repo):
        p = _insert_person(sa_sync_conn)
        with pytest.raises(NotFoundError):
            merge_person(p, 999999, repo=repo)


# ── batch_assign_orphan_authorships ─────────────────────────────────


class TestBatchAssignOrphanAuthorships:
    def test_empty_list_returns_zero(self, sa_sync_conn, repo, authorship_repo):
        _setup_uca(sa_sync_conn)
        person_id = _insert_person(sa_sync_conn)
        assert (
            batch_assign_orphan_authorships(
                person_id, [], repo=repo, authorship_repo=authorship_repo
            )
            == 0
        )

    def test_assigns_and_creates_authorship(self, sa_sync_conn, repo, authorship_repo):
        _setup_uca(sa_sync_conn)
        person_id = _insert_person(sa_sync_conn)
        pub_id = _insert_publication(sa_sync_conn)
        sp_hal = _insert_source_publication(sa_sync_conn, pub_id, source="hal", source_id="h-1")
        sp_oa = _insert_source_publication(sa_sync_conn, pub_id, source="openalex", source_id="W1")
        sa1 = _insert_source_authorship(
            sa_sync_conn, sp_hal, source="hal", author_name_normalized="jean dupont"
        )
        sa2 = _insert_source_authorship(
            sa_sync_conn,
            sp_oa,
            source="openalex",
            author_name_normalized="jean dupont",
        )

        assigned = batch_assign_orphan_authorships(
            person_id, [sa1, sa2], repo=repo, authorship_repo=authorship_repo
        )

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

    def test_skips_already_assigned(self, sa_sync_conn, repo, authorship_repo):
        _setup_uca(sa_sync_conn)
        p1 = _insert_person(sa_sync_conn, "A", "A")
        p2 = _insert_person(sa_sync_conn, "B", "B")
        pub_id = _insert_publication(sa_sync_conn)
        sp_id = _insert_source_publication(sa_sync_conn, pub_id)
        sa1 = _insert_source_authorship(sa_sync_conn, sp_id, person_id=p1)

        assigned = batch_assign_orphan_authorships(
            p2, [sa1], repo=repo, authorship_repo=authorship_repo
        )

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
        auth_id = sa_sync_conn.execute(
            text(
                "INSERT INTO authorships (publication_id, person_id) "
                "VALUES (:pub, :pid) RETURNING id"
            ),
            {"pub": pub_id, "pid": person_id},
        ).scalar_one()
        sa_id = _insert_source_authorship(sa_sync_conn, sp_id, person_id=person_id)

        result = detach_authorships(
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

    def test_detaches_all_sources_of_publication_from_single_ref(
        self, sa_sync_conn, repo, authorship_repo
    ):
        """Le rejet porte sur la publication entière : sélectionner une source
        détache toutes les sources de la même paire et peuple le store."""
        person_id = _insert_person(sa_sync_conn)
        pub_id = _insert_publication(sa_sync_conn)
        auth_id = sa_sync_conn.execute(
            text(
                "INSERT INTO authorships (publication_id, person_id) "
                "VALUES (:pub, :pid) RETURNING id"
            ),
            {"pub": pub_id, "pid": person_id},
        ).scalar_one()
        sp_hal = _insert_source_publication(sa_sync_conn, pub_id, source="hal", source_id="hal-1")
        sp_oa = _insert_source_publication(
            sa_sync_conn, pub_id, source="openalex", source_id="oa-1"
        )
        sa_hal = _insert_source_authorship(sa_sync_conn, sp_hal, source="hal", person_id=person_id)
        sa_oa = _insert_source_authorship(
            sa_sync_conn, sp_oa, source="openalex", person_id=person_id
        )

        # Une seule source sélectionnée (la hal).
        result = detach_authorships(
            person_id,
            authorships=[{"source": "hal", "authorship_id": sa_hal}],
            repo=repo,
            authorship_repo=authorship_repo,
        )

        assert result["detached"] == 2
        assert result["deleted_authorships"] == 1
        for sa_id in (sa_hal, sa_oa):
            assert (
                _scalar(
                    sa_sync_conn, "SELECT person_id FROM source_authorships WHERE id = :i", i=sa_id
                )
                is None
            )
        assert _scalar(sa_sync_conn, "SELECT id FROM authorships WHERE id = :i", i=auth_id) is None
        assert (
            _scalar(
                sa_sync_conn,
                "SELECT 1 FROM rejected_authorships WHERE publication_id = :p AND person_id = :pid",
                p=pub_id,
                pid=person_id,
            )
            == 1
        )

    def test_cleans_orphan_source_name_form(self, sa_sync_conn, repo, authorship_repo):
        """Une forme de nom attestée par une source, devenue sans aucune source
        active après détachement, est supprimée."""
        person_id = _insert_person(sa_sync_conn)
        pub_id = _insert_publication(sa_sync_conn)
        sp_id = _insert_source_publication(sa_sync_conn, pub_id)
        sa_id = _insert_source_authorship(
            sa_sync_conn, sp_id, person_id=person_id, author_name_normalized="dupont jean"
        )
        repo.add_name_form(person_id, "Dupont Jean", source="hal")

        result = detach_authorships(
            person_id,
            authorships=[{"source": "hal", "authorship_id": sa_id}],
            repo=repo,
            authorship_repo=authorship_repo,
        )
        assert result["cleaned_forms"] == 1
        assert (
            _scalar(
                sa_sync_conn,
                "SELECT 1 FROM person_name_forms WHERE name_form='dupont jean' AND person_id=:p",
                p=person_id,
            )
            is None
        )

    def test_preserves_rejected_orphan_name_form(self, sa_sync_conn, repo, authorship_repo):
        """Une forme `rejected` devenue orpheline est préservée : la supprimer
        détruirait le blocage de non-retour qu'elle matérialise."""
        person_id = _insert_person(sa_sync_conn)
        pub_id = _insert_publication(sa_sync_conn)
        sp_id = _insert_source_publication(sa_sync_conn, pub_id)
        sa_id = _insert_source_authorship(
            sa_sync_conn, sp_id, person_id=person_id, author_name_normalized="dupont jean"
        )
        repo.add_name_form(person_id, "Dupont Jean", source="hal")
        sa_sync_conn.execute(
            text(
                "UPDATE person_name_forms SET status='rejected' "
                "WHERE name_form='dupont jean' AND person_id=:p"
            ),
            {"p": person_id},
        )

        result = detach_authorships(
            person_id,
            authorships=[{"source": "hal", "authorship_id": sa_id}],
            repo=repo,
            authorship_repo=authorship_repo,
        )
        assert result["cleaned_forms"] == 0
        assert (
            _scalar(
                sa_sync_conn,
                "SELECT 1 FROM person_name_forms WHERE name_form='dupont jean' AND person_id=:p",
                p=person_id,
            )
            == 1
        )

    def test_preserves_computed_name_form(self, sa_sync_conn, repo, authorship_repo):
        """Les formes calculées depuis le nom de la personne (source `persons`)
        ne dépendent d'aucune source et survivent au détachement."""
        person_id = create_person("Dupont", "Jean", repo=repo)

        result = detach_authorships(
            person_id, authorships=[], repo=repo, authorship_repo=authorship_repo
        )
        assert result["cleaned_forms"] == 0
        assert (
            _scalar(
                sa_sync_conn,
                "SELECT 1 FROM person_name_forms WHERE name_form='dupont jean' AND person_id=:p",
                p=person_id,
            )
            == 1
        )

    def test_keeps_source_name_form_still_backed(self, sa_sync_conn, repo, authorship_repo):
        """Une forme encore attestée par une source d'une autre publication
        n'est pas supprimée quand on détache une seule publication."""
        person_id = _insert_person(sa_sync_conn)
        pub1 = _insert_publication(sa_sync_conn, "P1")
        pub2 = _insert_publication(sa_sync_conn, "P2")
        sp1 = _insert_source_publication(sa_sync_conn, pub1, source_id="hal-1")
        sp2 = _insert_source_publication(sa_sync_conn, pub2, source_id="hal-2")
        sa1 = _insert_source_authorship(
            sa_sync_conn, sp1, person_id=person_id, author_name_normalized="dupont jean"
        )
        _insert_source_authorship(
            sa_sync_conn, sp2, person_id=person_id, author_name_normalized="dupont jean"
        )
        repo.add_name_form(person_id, "Dupont Jean", source="hal")

        result = detach_authorships(
            person_id,
            authorships=[{"source": "hal", "authorship_id": sa1}],
            repo=repo,
            authorship_repo=authorship_repo,
        )
        assert result["cleaned_forms"] == 0
        assert (
            _scalar(
                sa_sync_conn,
                "SELECT 1 FROM person_name_forms WHERE name_form='dupont jean' AND person_id=:p",
                p=person_id,
            )
            == 1
        )


class TestMarkDistinctPersons:
    def test_raises_on_same_id(self, sa_sync_conn, repo):
        p = _insert_person(sa_sync_conn)
        with pytest.raises(ValidationError, match="elle-même"):
            mark_distinct(p, p, repo=repo)

    def test_inserts_ordered_pair(self, sa_sync_conn, repo):
        p1 = _insert_person(sa_sync_conn, "A", "A")
        p2 = _insert_person(sa_sync_conn, "B", "B")
        mark_distinct(p2, p1, repo=repo)
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
        mark_distinct(p1, p2, repo=repo)
        mark_distinct(p1, p2, repo=repo)
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
            {"source": "hal", "orcid": "0000-0001-2345-6789", "idhal": "jdupont"},
            {"source": "scanr", "orcid": "0000-0001-2345-6789", "idref": "252404955"},
        ]
        add_identifiers_from_authorships(person_id, authorships, repo=repo)

        rows = sa_sync_conn.execute(
            text(
                "SELECT id_type, id_value, source FROM person_identifiers "
                "WHERE person_id = :pid ORDER BY id_type"
            ),
            {"pid": person_id},
        ).all()
        id_types = [r.id_type for r in rows]
        assert id_types == ["idhal", "idref", "orcid"]

    def test_skips_malformed_and_keeps_valid(self, sa_sync_conn, repo):
        """Un identifiant source mal formé est ignoré (log, pas d'exception) ; la
        promotion continue pour les identifiants valides du même lot."""
        person_id = _insert_person(sa_sync_conn)
        authorships = [
            {"source": "hal", "orcid": "pas-un-orcid", "idhal": "jdupont"},
        ]
        add_identifiers_from_authorships(person_id, authorships, repo=repo)

        rows = sa_sync_conn.execute(
            text("SELECT id_type FROM person_identifiers WHERE person_id = :pid ORDER BY id_type"),
            {"pid": person_id},
        ).all()
        assert [r.id_type for r in rows] == ["idhal"]


# ── update_name_form_status ────────────────────────────────────────


class TestUpdateNameFormStatus:
    def test_reject_keeps_row_and_sets_status(self, sa_sync_conn, repo):
        """Rejeter une forme conserve la row (tombstone du verrou de non-retour),
        contrairement à l'ancien détachement par DELETE."""
        person_id = create_person("Unique", "Name", repo=repo)

        row = update_name_form_status(person_id, "name unique", "rejected", repo=repo)

        assert row["status"] == "rejected"
        db = sa_sync_conn.execute(
            text(
                "SELECT status::text AS s FROM person_name_forms "
                "WHERE name_form = 'name unique' AND person_id = :p"
            ),
            {"p": person_id},
        ).one()
        assert db.s == "rejected"

    def test_confirm_overrides_previous_status(self, repo):
        person_id = create_person("Alpha", "Beta", repo=repo)

        update_name_form_status(person_id, "alpha beta", "rejected", repo=repo)
        row = update_name_form_status(person_id, "alpha beta", "confirmed", repo=repo)

        assert row["status"] == "confirmed"

    def test_unknown_form_raises(self, repo):
        person_id = create_person("Gamma", "Delta", repo=repo)

        with pytest.raises(NotFoundError):
            update_name_form_status(person_id, "inexistante xyz", "rejected", repo=repo)

    def test_reject_detaches_authorships(self, sa_sync_conn, repo, authorship_repo):
        """Rejeter une forme détache ses signatures (source_authorships → NULL) et
        supprime les authorships canoniques devenues sans source ; le verrou reste posé."""
        pid = _insert_person(sa_sync_conn, "Foreign", "Form")
        sa_sync_conn.execute(
            text(
                "INSERT INTO person_name_forms (name_form, person_id, sources, status) "
                "VALUES ('intrus etranger', :pid, '{hal}', 'pending')"
            ),
            {"pid": pid},
        )
        pub = _insert_publication(sa_sync_conn)
        spid = _insert_source_publication(sa_sync_conn, pub)
        sa_id = _insert_source_authorship(
            sa_sync_conn, spid, person_id=pid, author_name_normalized="intrus etranger"
        )
        sa_sync_conn.execute(
            text("INSERT INTO authorships (publication_id, person_id) VALUES (:p, :pid)"),
            {"p": pub, "pid": pid},
        )

        update_name_form_status(
            pid, "intrus etranger", "rejected", repo=repo, authorship_repo=authorship_repo
        )

        assert (
            sa_sync_conn.execute(
                text("SELECT person_id FROM source_authorships WHERE id = :id"), {"id": sa_id}
            ).scalar_one()
            is None
        )
        assert (
            sa_sync_conn.execute(
                text("SELECT 1 FROM authorships WHERE publication_id = :p AND person_id = :pid"),
                {"p": pub, "pid": pid},
            ).first()
            is None
        )
        assert (
            sa_sync_conn.execute(
                text(
                    "SELECT status::text FROM person_name_forms "
                    "WHERE name_form = 'intrus etranger' AND person_id = :pid"
                ),
                {"pid": pid},
            ).scalar_one()
            == "rejected"
        )


# ── assign_orphan_authorship ───────────────────────────────────────


class TestAssignOrphanAuthorship:
    def test_raises_on_invalid_source(self, sa_sync_conn, repo, authorship_repo):
        with pytest.raises(ValidationError, match="Source inconnue"):
            assign_orphan_authorship(1, "invalid", 1, repo=repo, authorship_repo=authorship_repo)

    def test_raises_if_already_assigned(self, sa_sync_conn, repo, authorship_repo):
        """Une signature déjà rattachée n'est pas reprise : le refus nomme la détentrice."""
        _setup_uca(sa_sync_conn)
        person_id = _insert_person(sa_sync_conn)
        other_id = _insert_person(sa_sync_conn, "Other", "Author")
        pub_id = _insert_publication(sa_sync_conn)
        sp_id = _insert_source_publication(sa_sync_conn, pub_id)
        sa_id = _insert_source_authorship(sa_sync_conn, sp_id, person_id=other_id)

        with pytest.raises(AuthorshipAlreadyAssignedError) as exc:
            assign_orphan_authorship(
                person_id, "hal", sa_id, repo=repo, authorship_repo=authorship_repo
            )
        assert exc.value.owner_person_id == other_id
        assert (
            _scalar(sa_sync_conn, "SELECT person_id FROM source_authorships WHERE id = :i", i=sa_id)
            == other_id
        )

    def test_raises_if_source_authorship_missing(self, sa_sync_conn, repo, authorship_repo):
        person_id = _insert_person(sa_sync_conn)
        with pytest.raises(NotFoundError):
            assign_orphan_authorship(
                person_id, "hal", 999999, repo=repo, authorship_repo=authorship_repo
            )

    def test_assigns_and_creates_authorship(self, sa_sync_conn, repo, authorship_repo):
        _setup_uca(sa_sync_conn)
        person_id = _insert_person(sa_sync_conn)
        pub_id = _insert_publication(sa_sync_conn)
        sp_id = _insert_source_publication(sa_sync_conn, pub_id)
        sa_id = _insert_source_authorship(sa_sync_conn, sp_id)

        assign_orphan_authorship(
            person_id, "hal", sa_id, repo=repo, authorship_repo=authorship_repo
        )

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


def _reject_pair(conn, pub_id, person_id):
    conn.execute(
        text("INSERT INTO rejected_authorships (publication_id, person_id) VALUES (:p, :pid)"),
        {"p": pub_id, "pid": person_id},
    )


class TestReassignRejectedPairUnit:
    """Pré-contrôle de rejet sur les chemins de réassignation orphan-authorships."""

    def test_assign_blocked_when_rejected(self, sa_sync_conn, repo, authorship_repo):
        _setup_uca(sa_sync_conn)
        person_id = _insert_person(sa_sync_conn)
        pub_id = _insert_publication(sa_sync_conn)
        sp_id = _insert_source_publication(sa_sync_conn, pub_id)
        sa_id = _insert_source_authorship(sa_sync_conn, sp_id)
        _reject_pair(sa_sync_conn, pub_id, person_id)

        with pytest.raises(RejectedPairError) as exc:
            assign_orphan_authorship(
                person_id, "hal", sa_id, repo=repo, authorship_repo=authorship_repo
            )
        pair = exc.value.rejected_pairs[0]
        assert pair["publication_id"] == pub_id
        assert pair["person_id"] == person_id
        assert pair["rejected_at"]
        # Source non assignée : on a levé avant la pose de person_id.
        assert (
            _scalar(sa_sync_conn, "SELECT person_id FROM source_authorships WHERE id = :i", i=sa_id)
            is None
        )

    def test_assign_forced_unrejects_and_recreates_canonical(
        self, sa_sync_conn, repo, authorship_repo
    ):
        _setup_uca(sa_sync_conn)
        person_id = _insert_person(sa_sync_conn)
        pub_id = _insert_publication(sa_sync_conn)
        sp_id = _insert_source_publication(sa_sync_conn, pub_id)
        sa_id = _insert_source_authorship(sa_sync_conn, sp_id)
        _reject_pair(sa_sync_conn, pub_id, person_id)

        assign_orphan_authorship(
            person_id, "hal", sa_id, repo=repo, authorship_repo=authorship_repo, force=True
        )

        # Rejet levé
        assert (
            _scalar(
                sa_sync_conn,
                "SELECT 1 FROM rejected_authorships WHERE publication_id = :p AND person_id = :pid",
                p=pub_id,
                pid=person_id,
            )
            is None
        )
        # Source assignée et canonique recréée
        assert (
            _scalar(sa_sync_conn, "SELECT person_id FROM source_authorships WHERE id = :i", i=sa_id)
            == person_id
        )
        assert (
            _scalar(
                sa_sync_conn,
                "SELECT id FROM authorships WHERE publication_id = :p AND person_id = :pid",
                p=pub_id,
                pid=person_id,
            )
            is not None
        )

    def test_batch_blocked_lists_all_rejected(self, sa_sync_conn, repo, authorship_repo):
        _setup_uca(sa_sync_conn)
        person_id = _insert_person(sa_sync_conn)
        pub1 = _insert_publication(sa_sync_conn, "P1")
        pub2 = _insert_publication(sa_sync_conn, "P2")
        sp1 = _insert_source_publication(sa_sync_conn, pub1, source_id="h-1")
        sp2 = _insert_source_publication(sa_sync_conn, pub2, source_id="h-2")
        sa1 = _insert_source_authorship(sa_sync_conn, sp1)
        sa2 = _insert_source_authorship(sa_sync_conn, sp2)
        _reject_pair(sa_sync_conn, pub1, person_id)

        with pytest.raises(RejectedPairError) as exc:
            batch_assign_orphan_authorships(
                person_id, [sa1, sa2], repo=repo, authorship_repo=authorship_repo
            )
        assert {p["publication_id"] for p in exc.value.rejected_pairs} == {pub1}
        # Rien d'assigné : on a levé avant la pose.
        for sa_id in (sa1, sa2):
            assert (
                _scalar(
                    sa_sync_conn, "SELECT person_id FROM source_authorships WHERE id = :i", i=sa_id
                )
                is None
            )

    def test_batch_forced_unrejects_all(self, sa_sync_conn, repo, authorship_repo):
        _setup_uca(sa_sync_conn)
        person_id = _insert_person(sa_sync_conn)
        pub1 = _insert_publication(sa_sync_conn, "P1")
        sp1 = _insert_source_publication(sa_sync_conn, pub1, source_id="h-1")
        sa1 = _insert_source_authorship(sa_sync_conn, sp1)
        _reject_pair(sa_sync_conn, pub1, person_id)

        assigned = batch_assign_orphan_authorships(
            person_id, [sa1], repo=repo, authorship_repo=authorship_repo, force=True
        )

        assert assigned == 1
        assert (
            _scalar(
                sa_sync_conn,
                "SELECT 1 FROM rejected_authorships WHERE publication_id = :p AND person_id = :pid",
                p=pub1,
                pid=person_id,
            )
            is None
        )
        assert (
            _scalar(
                sa_sync_conn,
                "SELECT id FROM authorships WHERE publication_id = :p AND person_id = :pid",
                p=pub1,
                pid=person_id,
            )
            is not None
        )


class TestMergePersonRejectedAuthorships:
    """La fusion transfère les rejets de l'absorbée vers l'absorbante (identité
    identique), avec dédoublonnage sur conflit de PK."""

    def test_transfers_and_dedups(self, sa_sync_conn, repo):
        target = _insert_person(sa_sync_conn, "Cible", "T")
        source = _insert_person(sa_sync_conn, "Source", "S")
        pub_shared = _insert_publication(sa_sync_conn, "Shared")
        pub_source_only = _insert_publication(sa_sync_conn, "SourceOnly")

        def _reject(person_id, publication_id):
            sa_sync_conn.execute(
                text(
                    "INSERT INTO rejected_authorships (publication_id, person_id) "
                    "VALUES (:pub, :pid)"
                ),
                {"pub": publication_id, "pid": person_id},
            )

        _reject(target, pub_shared)  # conflit : déjà rejeté côté cible
        _reject(source, pub_shared)  # doit être dédoublonné
        _reject(source, pub_source_only)  # doit migrer vers la cible

        merge_person(target, source, repo=repo)

        rows = sa_sync_conn.execute(
            text(
                "SELECT publication_id, person_id FROM rejected_authorships ORDER BY publication_id"
            )
        ).all()
        assert {(r.publication_id, r.person_id) for r in rows} == {
            (pub_shared, target),
            (pub_source_only, target),
        }
