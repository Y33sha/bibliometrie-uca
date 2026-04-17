"""Tests de caractérisation pour services/structures.py.

Couvre create/update/delete sur structures, structure_relations,
structure_name_forms.
"""

import pytest

from services.structures import (
    create_name_form,
    create_relation,
    create_structure,
    delete_name_form,
    delete_relation,
    delete_structure,
    update_name_form,
    update_structure,
)

# ── structures ────────────────────────────────────────────────────

class TestCreateStructure:
    def test_minimal(self, db):
        row = create_structure(db, code="UCA", name="Université", type="universite")
        assert row["code"] == "UCA"
        assert row["name"] == "Université"
        assert row["type"] == "universite"
        assert row["acronym"] is None

    def test_with_api_ids(self, db):
        row = create_structure(
            db, code="TEST", name="Test", type="labo",
            api_ids={"openalex": ["I1"], "wos": ["WOS_TEST"]},
        )
        assert row["api_ids"] == {"openalex": ["I1"], "wos": ["WOS_TEST"]}


class TestUpdateStructure:
    def test_returns_none_if_not_found(self, db):
        assert update_structure(db, 999999, fields={"name": "X"}) is None

    def test_raises_on_empty_fields(self, db):
        row = create_structure(db, code="X", name="X", type="labo")
        with pytest.raises(ValueError, match="Aucun champ"):
            update_structure(db, row["id"], fields={})

    def test_updates_fields(self, db):
        row = create_structure(db, code="X", name="Ancien", type="labo")
        updated = update_structure(
            db, row["id"], fields={"name": "Nouveau", "acronym": "N"},
        )
        assert updated["name"] == "Nouveau"
        assert updated["acronym"] == "N"

    def test_updates_api_ids_replaces_dict(self, db):
        row = create_structure(db, code="X", name="X", type="labo",
                               api_ids={"openalex": ["OLD"]})
        updated = update_structure(db, row["id"], fields={"api_ids": {"openalex": ["NEW"]}})
        assert updated["api_ids"] == {"openalex": ["NEW"]}

    def test_none_fields_are_ignored(self, db):
        """Les champs à None dans le dict ne sont pas appliqués."""
        row = create_structure(db, code="X", name="Original", type="labo")
        updated = update_structure(
            db, row["id"], fields={"name": None, "acronym": "AC"},
        )
        assert updated["name"] == "Original"  # inchangé
        assert updated["acronym"] == "AC"


class TestDeleteStructure:
    def test_returns_false_if_not_found(self, db):
        assert delete_structure(db, 999999) is False

    def test_deletes_existing(self, db):
        row = create_structure(db, code="X", name="X", type="labo")
        assert delete_structure(db, row["id"]) is True
        db.execute("SELECT id FROM structures WHERE id = %s", (row["id"],))
        assert db.fetchone() is None


# ── structure_relations ───────────────────────────────────────────

class TestCreateRelation:
    def test_creates(self, db):
        parent = create_structure(db, code="P", name="Parent", type="universite")
        child = create_structure(db, code="C", name="Child", type="labo")
        rel = create_relation(
            db, parent_id=parent["id"], child_id=child["id"],
            relation_type="est_tutelle_de",
        )
        assert rel is not None
        assert rel["parent_id"] == parent["id"]
        assert rel["child_id"] == child["id"]

    def test_returns_none_on_conflict(self, db):
        """Si la relation existe déjà, retourne None (ON CONFLICT DO NOTHING)."""
        parent = create_structure(db, code="P", name="P", type="universite")
        child = create_structure(db, code="C", name="C", type="labo")
        create_relation(db, parent_id=parent["id"], child_id=child["id"],
                        relation_type="est_tutelle_de")
        again = create_relation(db, parent_id=parent["id"], child_id=child["id"],
                                relation_type="est_tutelle_de")
        assert again is None


class TestDeleteRelation:
    def test_returns_false_if_not_found(self, db):
        assert delete_relation(db, 999999) is False

    def test_deletes_existing(self, db):
        parent = create_structure(db, code="P", name="P", type="universite")
        child = create_structure(db, code="C", name="C", type="labo")
        rel = create_relation(db, parent_id=parent["id"], child_id=child["id"],
                              relation_type="est_tutelle_de")
        assert delete_relation(db, rel["id"]) is True


# ── structure_name_forms ──────────────────────────────────────────

class TestCreateNameForm:
    def test_creates_with_normalization(self, db):
        s = create_structure(db, code="X", name="X", type="labo")
        form = create_name_form(db, structure_id=s["id"], form_text="École UCA")
        # Le form_text est normalisé
        assert form["form_text"] == "ecole uca"
        assert form["is_word_boundary"] is False
        assert form["is_excluding"] is False

    def test_creates_with_context(self, db):
        s = create_structure(db, code="X", name="X", type="labo")
        form = create_name_form(
            db, structure_id=s["id"], form_text="U999",
            is_word_boundary=True, requires_context_of=[s["id"]],
        )
        assert form["is_word_boundary"] is True
        assert form["requires_context_of"] == [s["id"]]


class TestUpdateNameForm:
    def test_returns_none_if_not_found(self, db):
        assert update_name_form(db, 999999, fields={"form_text": "x"}) is None

    def test_raises_on_empty_fields(self, db):
        s = create_structure(db, code="X", name="X", type="labo")
        form = create_name_form(db, structure_id=s["id"], form_text="x")
        with pytest.raises(ValueError):
            update_name_form(db, form["id"], fields={})

    def test_updates_form_text_with_normalization(self, db):
        s = create_structure(db, code="X", name="X", type="labo")
        form = create_name_form(db, structure_id=s["id"], form_text="old")
        updated = update_name_form(db, form["id"], fields={"form_text": "École NEW"})
        assert updated["form_text"] == "ecole new"

    def test_updates_flags(self, db):
        s = create_structure(db, code="X", name="X", type="labo")
        form = create_name_form(db, structure_id=s["id"], form_text="x")
        updated = update_name_form(
            db, form["id"], fields={"is_word_boundary": True, "is_excluding": True},
        )
        assert updated["is_word_boundary"] is True
        assert updated["is_excluding"] is True


class TestDeleteNameForm:
    def test_returns_false_if_not_found(self, db):
        assert delete_name_form(db, 999999) is False

    def test_deletes_existing(self, db):
        s = create_structure(db, code="X", name="X", type="labo")
        form = create_name_form(db, structure_id=s["id"], form_text="x")
        assert delete_name_form(db, form["id"]) is True
