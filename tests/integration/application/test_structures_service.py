"""Tests de caractérisation pour application/structures.py.

Couvre create/update/delete sur structures, structure_relations,
structure_name_forms.
"""

import pytest
from sqlalchemy import text

from application.structures import (
    create_name_form,
    create_relation,
    create_structure,
    delete_name_form,
    delete_relation,
    delete_structure,
    update_name_form,
    update_structure,
)
from domain.errors import NotFoundError, ValidationError
from infrastructure.repositories import structure_repository


@pytest.fixture
def repo(sa_sync_conn):
    return structure_repository(sa_sync_conn)


# ── structures ────────────────────────────────────────────────────


class TestCreateStructure:
    def test_minimal(self, sa_sync_conn, repo):
        row = create_structure(
            sa_sync_conn, code="UCA", name="Université", type="universite", repo=repo
        )
        assert row["code"] == "UCA"
        assert row["name"] == "Université"
        assert row["type"] == "universite"
        assert row["acronym"] is None

    def test_with_api_ids(self, sa_sync_conn, repo):
        row = create_structure(
            sa_sync_conn,
            code="TEST",
            name="Test",
            type="labo",
            api_ids={"openalex": ["I1"], "wos": ["WOS_TEST"]},
            repo=repo,
        )
        assert row["api_ids"] == {"openalex": ["I1"], "wos": ["WOS_TEST"]}

    def test_api_ids_validated_and_coerced(self, sa_sync_conn, repo):
        """Un scalaire string passé pour une source est wrappé en liste via
        StructureApiIds. Les listes vides sont éliminées à la normalisation."""
        row = create_structure(
            sa_sync_conn,
            code="T2",
            name="T2",
            type="labo",
            api_ids={"openalex": "I1", "wos": []},
            repo=repo,
        )
        assert row["api_ids"] == {"openalex": ["I1"]}

    def test_api_ids_invalid_raises(self, sa_sync_conn, repo):
        """Un type aberrant (int dans une liste de strings) est rejeté."""
        with pytest.raises(ValidationError, match="api_ids invalide"):
            create_structure(
                sa_sync_conn,
                code="T3",
                name="T3",
                type="labo",
                api_ids={"openalex": [123, 456]},
                repo=repo,
            )


class TestUpdateStructure:
    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            update_structure(sa_sync_conn, 999999, fields={"name": "X"}, repo=repo)

    def test_raises_on_empty_fields(self, sa_sync_conn, repo):
        row = create_structure(sa_sync_conn, code="X", name="X", type="labo", repo=repo)
        with pytest.raises(ValidationError, match="Aucun champ"):
            update_structure(sa_sync_conn, row["id"], fields={}, repo=repo)

    def test_updates_fields(self, sa_sync_conn, repo):
        row = create_structure(sa_sync_conn, code="X", name="Ancien", type="labo", repo=repo)
        updated = update_structure(
            sa_sync_conn,
            row["id"],
            fields={"name": "Nouveau", "acronym": "N"},
            repo=repo,
        )
        assert updated["name"] == "Nouveau"
        assert updated["acronym"] == "N"

    def test_updates_api_ids_replaces_dict(self, sa_sync_conn, repo):
        row = create_structure(
            sa_sync_conn,
            code="X",
            name="X",
            type="labo",
            api_ids={"openalex": ["OLD"]},
            repo=repo,
        )
        updated = update_structure(
            sa_sync_conn, row["id"], fields={"api_ids": {"openalex": ["NEW"]}}, repo=repo
        )
        assert updated["api_ids"] == {"openalex": ["NEW"]}

    def test_none_fields_are_ignored(self, sa_sync_conn, repo):
        """Les champs à None dans le dict ne sont pas appliqués."""
        row = create_structure(sa_sync_conn, code="X", name="Original", type="labo", repo=repo)
        updated = update_structure(
            sa_sync_conn,
            row["id"],
            fields={"name": None, "acronym": "AC"},
            repo=repo,
        )
        assert updated["name"] == "Original"  # inchangé
        assert updated["acronym"] == "AC"


class TestDeleteStructure:
    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            delete_structure(sa_sync_conn, 999999, repo=repo)

    def test_deletes_existing(self, sa_sync_conn, repo):
        row = create_structure(sa_sync_conn, code="X", name="X", type="labo", repo=repo)
        delete_structure(sa_sync_conn, row["id"], repo=repo)
        result = sa_sync_conn.execute(
            text("SELECT id FROM structures WHERE id = :id"), {"id": row["id"]}
        )
        assert result.first() is None


# ── structure_relations ───────────────────────────────────────────


class TestCreateRelation:
    def test_creates(self, sa_sync_conn, repo):
        parent = create_structure(
            sa_sync_conn, code="P", name="Parent", type="universite", repo=repo
        )
        child = create_structure(sa_sync_conn, code="C", name="Child", type="labo", repo=repo)
        rel = create_relation(
            sa_sync_conn,
            parent_id=parent["id"],
            child_id=child["id"],
            relation_type="est_tutelle_de",
            repo=repo,
        )
        assert rel is not None
        assert rel["parent_id"] == parent["id"]
        assert rel["child_id"] == child["id"]

    def test_returns_none_on_conflict(self, sa_sync_conn, repo):
        """Si la relation existe déjà, retourne None (ON CONFLICT DO NOTHING)."""
        parent = create_structure(sa_sync_conn, code="P", name="P", type="universite", repo=repo)
        child = create_structure(sa_sync_conn, code="C", name="C", type="labo", repo=repo)
        create_relation(
            sa_sync_conn,
            parent_id=parent["id"],
            child_id=child["id"],
            relation_type="est_tutelle_de",
            repo=repo,
        )
        again = create_relation(
            sa_sync_conn,
            parent_id=parent["id"],
            child_id=child["id"],
            relation_type="est_tutelle_de",
            repo=repo,
        )
        assert again is None


class TestDeleteRelation:
    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            delete_relation(sa_sync_conn, 999999, repo=repo)

    def test_deletes_existing(self, sa_sync_conn, repo):
        parent = create_structure(sa_sync_conn, code="P", name="P", type="universite", repo=repo)
        child = create_structure(sa_sync_conn, code="C", name="C", type="labo", repo=repo)
        rel = create_relation(
            sa_sync_conn,
            parent_id=parent["id"],
            child_id=child["id"],
            relation_type="est_tutelle_de",
            repo=repo,
        )
        delete_relation(sa_sync_conn, rel["id"], repo=repo)
        result = sa_sync_conn.execute(
            text("SELECT id FROM structure_relations WHERE id = :id"), {"id": rel["id"]}
        )
        assert result.first() is None


# ── structure_name_forms ──────────────────────────────────────────


class TestCreateNameForm:
    def test_creates_with_normalization(self, sa_sync_conn, repo):
        s = create_structure(sa_sync_conn, code="X", name="X", type="labo", repo=repo)
        form = create_name_form(
            sa_sync_conn, structure_id=s["id"], form_text="École UCA", repo=repo
        )
        # Le form_text est normalisé
        assert form["form_text"] == "ecole uca"
        assert form["is_word_boundary"] is False
        assert form["is_excluding"] is False

    def test_creates_with_context(self, sa_sync_conn, repo):
        s = create_structure(sa_sync_conn, code="X", name="X", type="labo", repo=repo)
        form = create_name_form(
            sa_sync_conn,
            structure_id=s["id"],
            form_text="U999",
            is_word_boundary=True,
            requires_context_of=[s["id"]],
            repo=repo,
        )
        assert form["is_word_boundary"] is True
        assert form["requires_context_of"] == [s["id"]]


class TestUpdateNameForm:
    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            update_name_form(sa_sync_conn, 999999, fields={"form_text": "x"}, repo=repo)

    def test_raises_on_empty_fields(self, sa_sync_conn, repo):
        s = create_structure(sa_sync_conn, code="X", name="X", type="labo", repo=repo)
        form = create_name_form(sa_sync_conn, structure_id=s["id"], form_text="x", repo=repo)
        with pytest.raises(ValidationError):
            update_name_form(sa_sync_conn, form["id"], fields={}, repo=repo)

    def test_updates_form_text_with_normalization(self, sa_sync_conn, repo):
        s = create_structure(sa_sync_conn, code="X", name="X", type="labo", repo=repo)
        form = create_name_form(sa_sync_conn, structure_id=s["id"], form_text="old", repo=repo)
        updated = update_name_form(
            sa_sync_conn, form["id"], fields={"form_text": "École NEW"}, repo=repo
        )
        assert updated["form_text"] == "ecole new"

    def test_updates_flags(self, sa_sync_conn, repo):
        s = create_structure(sa_sync_conn, code="X", name="X", type="labo", repo=repo)
        form = create_name_form(sa_sync_conn, structure_id=s["id"], form_text="x", repo=repo)
        updated = update_name_form(
            sa_sync_conn,
            form["id"],
            fields={"is_word_boundary": True, "is_excluding": True},
            repo=repo,
        )
        assert updated["is_word_boundary"] is True
        assert updated["is_excluding"] is True


class TestDeleteNameForm:
    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            delete_name_form(sa_sync_conn, 999999, repo=repo)

    def test_deletes_existing(self, sa_sync_conn, repo):
        s = create_structure(sa_sync_conn, code="X", name="X", type="labo", repo=repo)
        form = create_name_form(sa_sync_conn, structure_id=s["id"], form_text="x", repo=repo)
        delete_name_form(sa_sync_conn, form["id"], repo=repo)
        result = sa_sync_conn.execute(
            text("SELECT id FROM structure_name_forms WHERE id = :id"), {"id": form["id"]}
        )
        assert result.first() is None
