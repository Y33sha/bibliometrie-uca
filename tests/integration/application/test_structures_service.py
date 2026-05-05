"""Tests de caractérisation pour application/structures.py (async).

Couvre create/update/delete sur structures, structure_relations,
structure_name_forms.
"""

import pytest

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
from infrastructure.repositories import async_structure_repository


@pytest.fixture
def repo(async_db):
    return async_structure_repository(async_db)


# ── structures ────────────────────────────────────────────────────


class TestCreateStructure:
    async def test_minimal(self, async_db, repo):
        row = await create_structure(
            async_db, code="UCA", name="Université", type="universite", repo=repo
        )
        assert row["code"] == "UCA"
        assert row["name"] == "Université"
        assert row["type"] == "universite"
        assert row["acronym"] is None

    async def test_with_api_ids(self, async_db, repo):
        row = await create_structure(
            async_db,
            code="TEST",
            name="Test",
            type="labo",
            api_ids={"openalex": ["I1"], "wos": ["WOS_TEST"]},
            repo=repo,
        )
        assert row["api_ids"] == {"openalex": ["I1"], "wos": ["WOS_TEST"]}

    async def test_api_ids_validated_and_coerced(self, async_db, repo):
        """Un scalaire string passé pour une source est wrappé en liste via
        StructureApiIds. Les listes vides sont éliminées à la normalisation."""
        row = await create_structure(
            async_db,
            code="T2",
            name="T2",
            type="labo",
            api_ids={"openalex": "I1", "wos": []},
            repo=repo,
        )
        assert row["api_ids"] == {"openalex": ["I1"]}

    async def test_api_ids_invalid_raises(self, async_db, repo):
        """Un type aberrant (int dans une liste de strings) est rejeté."""
        with pytest.raises(ValidationError, match="api_ids invalide"):
            await create_structure(
                async_db,
                code="T3",
                name="T3",
                type="labo",
                api_ids={"openalex": [123, 456]},
                repo=repo,
            )


class TestUpdateStructure:
    async def test_raises_not_found(self, async_db, repo):
        with pytest.raises(NotFoundError):
            await update_structure(async_db, 999999, fields={"name": "X"}, repo=repo)

    async def test_raises_on_empty_fields(self, async_db, repo):
        row = await create_structure(async_db, code="X", name="X", type="labo", repo=repo)
        with pytest.raises(ValidationError, match="Aucun champ"):
            await update_structure(async_db, row["id"], fields={}, repo=repo)

    async def test_updates_fields(self, async_db, repo):
        row = await create_structure(async_db, code="X", name="Ancien", type="labo", repo=repo)
        updated = await update_structure(
            async_db,
            row["id"],
            fields={"name": "Nouveau", "acronym": "N"},
            repo=repo,
        )
        assert updated["name"] == "Nouveau"
        assert updated["acronym"] == "N"

    async def test_updates_api_ids_replaces_dict(self, async_db, repo):
        row = await create_structure(
            async_db,
            code="X",
            name="X",
            type="labo",
            api_ids={"openalex": ["OLD"]},
            repo=repo,
        )
        updated = await update_structure(
            async_db, row["id"], fields={"api_ids": {"openalex": ["NEW"]}}, repo=repo
        )
        assert updated["api_ids"] == {"openalex": ["NEW"]}

    async def test_none_fields_are_ignored(self, async_db, repo):
        """Les champs à None dans le dict ne sont pas appliqués."""
        row = await create_structure(async_db, code="X", name="Original", type="labo", repo=repo)
        updated = await update_structure(
            async_db,
            row["id"],
            fields={"name": None, "acronym": "AC"},
            repo=repo,
        )
        assert updated["name"] == "Original"  # inchangé
        assert updated["acronym"] == "AC"


class TestDeleteStructure:
    async def test_raises_not_found(self, async_db, repo):
        with pytest.raises(NotFoundError):
            await delete_structure(async_db, 999999, repo=repo)

    async def test_deletes_existing(self, async_db, repo):
        row = await create_structure(async_db, code="X", name="X", type="labo", repo=repo)
        await delete_structure(async_db, row["id"], repo=repo)
        await async_db.execute("SELECT id FROM structures WHERE id = %s", (row["id"],))
        assert await async_db.fetchone() is None


# ── structure_relations ───────────────────────────────────────────


class TestCreateRelation:
    async def test_creates(self, async_db, repo):
        parent = await create_structure(
            async_db, code="P", name="Parent", type="universite", repo=repo
        )
        child = await create_structure(async_db, code="C", name="Child", type="labo", repo=repo)
        rel = await create_relation(
            async_db,
            parent_id=parent["id"],
            child_id=child["id"],
            relation_type="est_tutelle_de",
            repo=repo,
        )
        assert rel is not None
        assert rel["parent_id"] == parent["id"]
        assert rel["child_id"] == child["id"]

    async def test_returns_none_on_conflict(self, async_db, repo):
        """Si la relation existe déjà, retourne None (ON CONFLICT DO NOTHING)."""
        parent = await create_structure(async_db, code="P", name="P", type="universite", repo=repo)
        child = await create_structure(async_db, code="C", name="C", type="labo", repo=repo)
        await create_relation(
            async_db,
            parent_id=parent["id"],
            child_id=child["id"],
            relation_type="est_tutelle_de",
            repo=repo,
        )
        again = await create_relation(
            async_db,
            parent_id=parent["id"],
            child_id=child["id"],
            relation_type="est_tutelle_de",
            repo=repo,
        )
        assert again is None


class TestDeleteRelation:
    async def test_raises_not_found(self, async_db, repo):
        with pytest.raises(NotFoundError):
            await delete_relation(async_db, 999999, repo=repo)

    async def test_deletes_existing(self, async_db, repo):
        parent = await create_structure(async_db, code="P", name="P", type="universite", repo=repo)
        child = await create_structure(async_db, code="C", name="C", type="labo", repo=repo)
        rel = await create_relation(
            async_db,
            parent_id=parent["id"],
            child_id=child["id"],
            relation_type="est_tutelle_de",
            repo=repo,
        )
        await delete_relation(async_db, rel["id"], repo=repo)
        await async_db.execute("SELECT id FROM structure_relations WHERE id = %s", (rel["id"],))
        assert await async_db.fetchone() is None


# ── structure_name_forms ──────────────────────────────────────────


class TestCreateNameForm:
    async def test_creates_with_normalization(self, async_db, repo):
        s = await create_structure(async_db, code="X", name="X", type="labo", repo=repo)
        form = await create_name_form(
            async_db, structure_id=s["id"], form_text="École UCA", repo=repo
        )
        # Le form_text est normalisé
        assert form["form_text"] == "ecole uca"
        assert form["is_word_boundary"] is False
        assert form["is_excluding"] is False

    async def test_creates_with_context(self, async_db, repo):
        s = await create_structure(async_db, code="X", name="X", type="labo", repo=repo)
        form = await create_name_form(
            async_db,
            structure_id=s["id"],
            form_text="U999",
            is_word_boundary=True,
            requires_context_of=[s["id"]],
            repo=repo,
        )
        assert form["is_word_boundary"] is True
        assert form["requires_context_of"] == [s["id"]]


class TestUpdateNameForm:
    async def test_raises_not_found(self, async_db, repo):
        with pytest.raises(NotFoundError):
            await update_name_form(async_db, 999999, fields={"form_text": "x"}, repo=repo)

    async def test_raises_on_empty_fields(self, async_db, repo):
        s = await create_structure(async_db, code="X", name="X", type="labo", repo=repo)
        form = await create_name_form(async_db, structure_id=s["id"], form_text="x", repo=repo)
        with pytest.raises(ValidationError):
            await update_name_form(async_db, form["id"], fields={}, repo=repo)

    async def test_updates_form_text_with_normalization(self, async_db, repo):
        s = await create_structure(async_db, code="X", name="X", type="labo", repo=repo)
        form = await create_name_form(async_db, structure_id=s["id"], form_text="old", repo=repo)
        updated = await update_name_form(
            async_db, form["id"], fields={"form_text": "École NEW"}, repo=repo
        )
        assert updated["form_text"] == "ecole new"

    async def test_updates_flags(self, async_db, repo):
        s = await create_structure(async_db, code="X", name="X", type="labo", repo=repo)
        form = await create_name_form(async_db, structure_id=s["id"], form_text="x", repo=repo)
        updated = await update_name_form(
            async_db,
            form["id"],
            fields={"is_word_boundary": True, "is_excluding": True},
            repo=repo,
        )
        assert updated["is_word_boundary"] is True
        assert updated["is_excluding"] is True


class TestDeleteNameForm:
    async def test_raises_not_found(self, async_db, repo):
        with pytest.raises(NotFoundError):
            await delete_name_form(async_db, 999999, repo=repo)

    async def test_deletes_existing(self, async_db, repo):
        s = await create_structure(async_db, code="X", name="X", type="labo", repo=repo)
        form = await create_name_form(async_db, structure_id=s["id"], form_text="x", repo=repo)
        await delete_name_form(async_db, form["id"], repo=repo)
        await async_db.execute("SELECT id FROM structure_name_forms WHERE id = %s", (form["id"],))
        assert await async_db.fetchone() is None
