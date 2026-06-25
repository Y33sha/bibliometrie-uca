"""Tests de caractérisation pour application/structures/core.py.

Couvre create/update/delete sur structures, structure_relations,
structure_name_forms.
"""

import pytest
from sqlalchemy import text

from application.structures.core import (
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
from domain.structures.identifiers import HalCollection, RorId
from domain.structures.structure import StructureType
from infrastructure.repositories import structure_repository


@pytest.fixture
def repo(sa_sync_conn):
    return structure_repository(sa_sync_conn)


# ── structures ────────────────────────────────────────────────────


class TestFindById:
    def test_returns_none_if_missing(self, sa_sync_conn, repo):
        assert repo.find_by_id(999999) is None

    def test_hydrates_minimal_structure(self, sa_sync_conn, repo):
        row = create_structure(code="MIN", name="Min", type="labo", repo=repo)
        s = repo.find_by_id(row["id"])
        assert s is not None
        assert s.id == row["id"]
        assert s.code == "MIN"
        assert s.name == "Min"
        assert s.structure_type is StructureType.LABO
        assert s.acronym is None
        assert s.ror_id is None
        assert s.hal_collection is None
        assert s.api_ids is None
        assert s.name_forms == ()

    def test_hydrates_full_structure_with_vos(self, sa_sync_conn, repo):
        row = create_structure(
            code="UMR-LIMOS",
            name="LIMOS",
            type="labo",
            acronym="LIMOS",
            ror_id="02feahw73",
            hal_collection="LIMOS",
            api_ids={"openalex": ["I1"], "wos": ["W1"]},
            repo=repo,
        )
        s = repo.find_by_id(row["id"])
        assert s is not None
        assert s.ror_id == RorId("02feahw73")
        assert s.hal_collection == HalCollection("LIMOS")
        assert s.api_ids == {"openalex": ["I1"], "wos": ["W1"]}

    def test_hydrates_name_forms(self, sa_sync_conn, repo):
        row = create_structure(code="S", name="S", type="labo", repo=repo)
        create_name_form(structure_id=row["id"], form_text="lab x", repo=repo)
        create_name_form(
            structure_id=row["id"],
            form_text="autre forme",
            is_word_boundary=True,
            repo=repo,
        )
        s = repo.find_by_id(row["id"])
        assert s is not None
        assert len(s.name_forms) == 2
        forms = {nf.form_text for nf in s.name_forms}
        assert forms == {"lab x", "autre forme"}


class TestCreateStructure:
    def test_minimal(self, sa_sync_conn, repo):
        row = create_structure(code="UCA", name="Université", type="universite", repo=repo)
        assert row["code"] == "UCA"
        assert row["name"] == "Université"
        assert row["type"] == "universite"
        assert row["acronym"] is None

    def test_with_api_ids(self, sa_sync_conn, repo):
        row = create_structure(
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
                code="T3",
                name="T3",
                type="labo",
                api_ids={"openalex": [123, 456]},
                repo=repo,
            )

    def test_ror_id_full_url_normalized_to_short(self, sa_sync_conn, repo):
        """Une URL ROR complète est ramenée à l'ID 9-char canonique (VO RorId),
        quelle que soit la forme envoyée par le client."""
        row = create_structure(
            code="ROR1",
            name="Ror1",
            type="labo",
            ror_id="https://ror.org/026tc4g97",
            repo=repo,
        )
        assert row["ror_id"] == "026tc4g97"

    def test_ror_id_invalid_raises(self, sa_sync_conn, repo):
        with pytest.raises(ValidationError, match="ror_id invalide"):
            create_structure(code="ROR2", name="Ror2", type="labo", ror_id="pas-un-ror", repo=repo)


class TestUpdateStructure:
    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            update_structure(999999, fields={"name": "X"}, repo=repo)

    def test_raises_on_empty_fields(self, sa_sync_conn, repo):
        row = create_structure(code="X", name="X", type="labo", repo=repo)
        with pytest.raises(ValidationError, match="Aucun champ"):
            update_structure(row["id"], fields={}, repo=repo)

    def test_updates_fields(self, sa_sync_conn, repo):
        row = create_structure(code="X", name="Ancien", type="labo", repo=repo)
        updated = update_structure(
            row["id"],
            fields={"name": "Nouveau", "acronym": "N"},
            repo=repo,
        )
        assert updated["name"] == "Nouveau"
        assert updated["acronym"] == "N"

    def test_updates_api_ids_replaces_dict(self, sa_sync_conn, repo):
        row = create_structure(
            code="X",
            name="X",
            type="labo",
            api_ids={"openalex": ["OLD"]},
            repo=repo,
        )
        updated = update_structure(row["id"], fields={"api_ids": {"openalex": ["NEW"]}}, repo=repo)
        assert updated["api_ids"] == {"openalex": ["NEW"]}

    def test_none_fields_are_ignored(self, sa_sync_conn, repo):
        """Les champs à None dans le dict ne sont pas appliqués."""
        row = create_structure(code="X", name="Original", type="labo", repo=repo)
        updated = update_structure(
            row["id"],
            fields={"name": None, "acronym": "AC"},
            repo=repo,
        )
        assert updated["name"] == "Original"  # inchangé
        assert updated["acronym"] == "AC"

    def test_ror_id_full_url_normalized_to_short(self, sa_sync_conn, repo):
        """Régression : éditer une structure en envoyant le ROR en URL complète
        (ce que faisait le form admin) ne doit plus stocker l'URL — le service la
        ramène à l'ID court via le VO RorId."""
        row = create_structure(code="X", name="X", type="labo", ror_id="026tc4g97", repo=repo)
        updated = update_structure(
            row["id"],
            fields={"acronym": "X", "ror_id": "https://ror.org/026tc4g97"},
            repo=repo,
        )
        assert updated["ror_id"] == "026tc4g97"

    def test_ror_id_invalid_raises(self, sa_sync_conn, repo):
        row = create_structure(code="X", name="X", type="labo", repo=repo)
        with pytest.raises(ValidationError, match="ror_id invalide"):
            update_structure(row["id"], fields={"ror_id": "pas-un-ror"}, repo=repo)


class TestDeleteStructure:
    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            delete_structure(999999, repo=repo)

    def test_deletes_existing(self, sa_sync_conn, repo):
        row = create_structure(code="X", name="X", type="labo", repo=repo)
        delete_structure(row["id"], repo=repo)
        result = sa_sync_conn.execute(
            text("SELECT id FROM structures WHERE id = :id"), {"id": row["id"]}
        )
        assert result.first() is None


# ── structure_relations ───────────────────────────────────────────


class TestCreateRelation:
    def test_creates(self, sa_sync_conn, repo):
        parent = create_structure(code="P", name="Parent", type="universite", repo=repo)
        child = create_structure(code="C", name="Child", type="labo", repo=repo)
        rel = create_relation(
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
        parent = create_structure(code="P", name="P", type="universite", repo=repo)
        child = create_structure(code="C", name="C", type="labo", repo=repo)
        create_relation(
            parent_id=parent["id"],
            child_id=child["id"],
            relation_type="est_tutelle_de",
            repo=repo,
        )
        again = create_relation(
            parent_id=parent["id"],
            child_id=child["id"],
            relation_type="est_tutelle_de",
            repo=repo,
        )
        assert again is None

    def test_rejects_self_reference(self, sa_sync_conn, repo):
        s = create_structure(code="S", name="S", type="universite", repo=repo)
        with pytest.raises(ValidationError, match="Auto-référence"):
            create_relation(
                parent_id=s["id"],
                child_id=s["id"],
                relation_type="est_tutelle_de",
                repo=repo,
            )

    def test_rejects_cycle(self, sa_sync_conn, repo):
        """A → B existe ; tenter B → A doit échouer (cycle)."""
        a = create_structure(code="A", name="A", type="universite", repo=repo)
        b = create_structure(code="B", name="B", type="labo", repo=repo)
        create_relation(
            parent_id=a["id"],
            child_id=b["id"],
            relation_type="est_tutelle_de",
            repo=repo,
        )
        with pytest.raises(ValidationError, match="Cycle"):
            create_relation(
                parent_id=b["id"],
                child_id=a["id"],
                relation_type="est_tutelle_de",
                repo=repo,
            )

    def test_rejects_indirect_cycle(self, sa_sync_conn, repo):
        """A → B → C ; tenter C → A doit échouer."""
        a = create_structure(code="A", name="A", type="universite", repo=repo)
        b = create_structure(code="B", name="B", type="labo", repo=repo)
        c = create_structure(code="C", name="C", type="equipe", repo=repo)
        create_relation(parent_id=a["id"], child_id=b["id"], relation_type="x", repo=repo)
        create_relation(parent_id=b["id"], child_id=c["id"], relation_type="x", repo=repo)
        with pytest.raises(ValidationError, match="Cycle"):
            create_relation(parent_id=c["id"], child_id=a["id"], relation_type="x", repo=repo)


class TestDeleteRelation:
    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            delete_relation(999999, repo=repo)

    def test_deletes_existing(self, sa_sync_conn, repo):
        parent = create_structure(code="P", name="P", type="universite", repo=repo)
        child = create_structure(code="C", name="C", type="labo", repo=repo)
        rel = create_relation(
            parent_id=parent["id"],
            child_id=child["id"],
            relation_type="est_tutelle_de",
            repo=repo,
        )
        delete_relation(rel["id"], repo=repo)
        result = sa_sync_conn.execute(
            text("SELECT id FROM structure_relations WHERE id = :id"), {"id": rel["id"]}
        )
        assert result.first() is None


# ── structure_name_forms ──────────────────────────────────────────


class TestCreateNameForm:
    def test_creates_with_normalization(self, sa_sync_conn, repo):
        s = create_structure(code="X", name="X", type="labo", repo=repo)
        form = create_name_form(structure_id=s["id"], form_text="École UCA", repo=repo)
        # Le form_text est normalisé
        assert form["form_text"] == "ecole uca"
        assert form["is_word_boundary"] is False
        assert form["is_excluding"] is False

    def test_creates_with_context(self, sa_sync_conn, repo):
        s = create_structure(code="X", name="X", type="labo", repo=repo)
        form = create_name_form(
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
            update_name_form(999999, fields={"form_text": "x"}, repo=repo)

    def test_raises_on_empty_fields(self, sa_sync_conn, repo):
        s = create_structure(code="X", name="X", type="labo", repo=repo)
        form = create_name_form(structure_id=s["id"], form_text="x", repo=repo)
        with pytest.raises(ValidationError):
            update_name_form(form["id"], fields={}, repo=repo)

    def test_updates_form_text_with_normalization(self, sa_sync_conn, repo):
        s = create_structure(code="X", name="X", type="labo", repo=repo)
        form = create_name_form(structure_id=s["id"], form_text="old", repo=repo)
        updated = update_name_form(form["id"], fields={"form_text": "École NEW"}, repo=repo)
        assert updated["form_text"] == "ecole new"

    def test_updates_flags(self, sa_sync_conn, repo):
        s = create_structure(code="X", name="X", type="labo", repo=repo)
        form = create_name_form(structure_id=s["id"], form_text="x", repo=repo)
        updated = update_name_form(
            form["id"],
            fields={"is_word_boundary": True, "is_excluding": True},
            repo=repo,
        )
        assert updated["is_word_boundary"] is True
        assert updated["is_excluding"] is True


class TestDeleteNameForm:
    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            delete_name_form(999999, repo=repo)

    def test_deletes_existing(self, sa_sync_conn, repo):
        s = create_structure(code="X", name="X", type="labo", repo=repo)
        form = create_name_form(structure_id=s["id"], form_text="x", repo=repo)
        delete_name_form(form["id"], repo=repo)
        result = sa_sync_conn.execute(
            text("SELECT id FROM structure_name_forms WHERE id = :id"), {"id": form["id"]}
        )
        assert result.first() is None
