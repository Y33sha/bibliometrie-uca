"""Tests de caractérisation pour application/services/structures.py.

Couvre create/update/delete sur structures, structure_parents,
structure_name_forms.
"""

import pytest
from sqlalchemy import text

from application.ports.repositories.structure_repository import (
    NameFormCreate,
    NameFormUpdate,
    StructureCreate,
    StructureUpdate,
)
from domain.errors import NotFoundError, ValidationError
from domain.structures.identifiers import HalCollection, RorId
from domain.structures.structure import StructureType
from infrastructure.read_models.structures.models import StructureOut
from infrastructure.repositories import structure_repository
from interfaces.api.deps import structure_service


def _create_structure(*, service, structure_type, **fields):
    """Crée une structure par le service, et rend sa réponse d'API en dict."""
    structure = service.create_structure(StructureCreate(type=structure_type, **fields))
    return StructureOut.from_structure(structure).model_dump()


def _update_structure(structure_id, *, update, service):
    """Met à jour une structure par le service, et rend sa réponse d'API en dict."""
    structure = service.update_structure(structure_id, update=update)
    return StructureOut.from_structure(structure).model_dump()


def _create_name_form(*, service, **fields):
    """Crée une forme de nom par le service."""
    return service.create_name_form(NameFormCreate(**fields))


@pytest.fixture
def repo(sa_sync_conn):
    return structure_repository(sa_sync_conn)


@pytest.fixture
def service(sa_sync_conn):
    return structure_service(sa_sync_conn)


# ── structures ────────────────────────────────────────────────────


class TestFindById:
    def test_returns_none_if_missing(self, sa_sync_conn, repo):
        assert repo.find_by_id(999999) is None

    def test_hydrates_minimal_structure(self, sa_sync_conn, repo, service):
        row = _create_structure(code="MIN", name="Min", structure_type="labo", service=service)
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

    def test_hydrates_full_structure_with_vos(self, sa_sync_conn, repo, service):
        row = _create_structure(
            code="UMR-LIMOS",
            name="LIMOS",
            structure_type="labo",
            acronym="LIMOS",
            ror_id="02feahw73",
            hal_collection="LIMOS",
            api_ids={"openalex": ["I1"], "wos": ["W1"]},
            service=service,
        )
        s = repo.find_by_id(row["id"])
        assert s is not None
        assert s.ror_id == RorId("02feahw73")
        assert s.hal_collection == HalCollection("LIMOS")
        assert s.api_ids == {"openalex": ["I1"], "wos": ["W1"]}

    def test_hydrates_name_forms(self, sa_sync_conn, repo, service):
        row = _create_structure(code="S", name="S", structure_type="labo", service=service)
        _create_name_form(structure_id=row["id"], form_text="lab x", service=service)
        _create_name_form(
            structure_id=row["id"],
            form_text="autre forme",
            is_word_boundary=True,
            service=service,
        )
        s = repo.find_by_id(row["id"])
        assert s is not None
        assert len(s.name_forms) == 2
        forms = {name_form.form_text for name_form in s.name_forms}
        assert forms == {"lab x", "autre forme"}


class TestCreateStructure:
    def test_minimal(self, sa_sync_conn, service):
        row = _create_structure(
            code="UCA", name="Université", structure_type="universite", service=service
        )
        assert row["code"] == "UCA"
        assert row["name"] == "Université"
        assert row["type"] == "universite"
        assert row["acronym"] is None

    def test_with_api_ids(self, sa_sync_conn, service):
        row = _create_structure(
            code="TEST",
            name="Test",
            structure_type="labo",
            api_ids={"openalex": ["I1"], "wos": ["WOS_TEST"]},
            service=service,
        )
        assert row["api_ids"] == {"openalex": ["I1"], "wos": ["WOS_TEST"]}

    def test_api_ids_validated_and_coerced(self, sa_sync_conn, service):
        """Un scalaire string passé pour une source est wrappé en liste via
        StructureApiIds. Les listes vides sont éliminées à la normalisation."""
        row = _create_structure(
            code="T2",
            name="T2",
            structure_type="labo",
            api_ids={"openalex": "I1", "wos": []},
            service=service,
        )
        assert row["api_ids"] == {"openalex": ["I1"]}

    def test_api_ids_invalid_raises(self, sa_sync_conn, service):
        """Un type aberrant (int dans une liste de strings) est rejeté par le repository, que le modèle ne valide pas ici."""
        create = StructureCreate.model_construct(
            code="T3", name="T3", type=StructureType.LABO, api_ids={"openalex": [123, 456]}
        )
        with pytest.raises(ValidationError, match="api_ids invalide"):
            service.create_structure(create)

    def test_ror_id_full_url_normalized_to_short(self, sa_sync_conn, service):
        """Une URL ROR complète est ramenée à l'ID 9-char canonique (VO RorId),
        quelle que soit la forme envoyée par le client."""
        row = _create_structure(
            code="ROR1",
            name="Ror1",
            structure_type="labo",
            ror_id="https://ror.org/026tc4g97",
            service=service,
        )
        assert row["ror_id"] == "026tc4g97"

    def test_ror_id_invalid_raises(self, sa_sync_conn, service):
        with pytest.raises(ValidationError, match="ror_id invalide"):
            _create_structure(
                code="ROR2",
                name="Ror2",
                structure_type="labo",
                ror_id="pas-un-ror",
                service=service,
            )


class TestUpdateStructure:
    def test_raises_not_found(self, sa_sync_conn, service):
        with pytest.raises(NotFoundError):
            _update_structure(999999, update=StructureUpdate(name="X"), service=service)

    def test_raises_on_empty_fields(self, sa_sync_conn, service):
        row = _create_structure(code="X", name="X", structure_type="labo", service=service)
        with pytest.raises(ValidationError, match="Aucun champ"):
            _update_structure(row["id"], update=StructureUpdate(), service=service)

    def test_updates_fields(self, sa_sync_conn, service):
        row = _create_structure(code="X", name="Ancien", structure_type="labo", service=service)
        updated = _update_structure(
            row["id"],
            update=StructureUpdate(name="Nouveau", acronym="N"),
            service=service,
        )
        assert updated["name"] == "Nouveau"
        assert updated["acronym"] == "N"

    def test_updates_api_ids_replaces_dict(self, sa_sync_conn, service):
        row = _create_structure(
            code="X",
            name="X",
            structure_type="labo",
            api_ids={"openalex": ["OLD"]},
            service=service,
        )
        updated = _update_structure(
            row["id"], update=StructureUpdate(api_ids={"openalex": ["NEW"]}), service=service
        )
        assert updated["api_ids"] == {"openalex": ["NEW"]}

    def test_null_name_is_ignored(self, sa_sync_conn, service):
        """Le nom est obligatoire : `null` vaut champ non fourni."""
        row = _create_structure(code="X", name="Original", structure_type="labo", service=service)
        updated = _update_structure(
            row["id"],
            update=StructureUpdate(name=None, acronym="AC"),
            service=service,
        )
        assert updated["name"] == "Original"
        assert updated["acronym"] == "AC"

    def test_null_clears_optional_fields(self, sa_sync_conn, service):
        """Le formulaire envoie `null` pour un acronyme, un ROR ou une collection HAL vidés."""
        row = _create_structure(
            code="X",
            name="X",
            structure_type="labo",
            acronym="LB",
            ror_id="026tc4g97",
            hal_collection="LIMOS",
            service=service,
        )
        updated = _update_structure(
            row["id"],
            update=StructureUpdate(name="X", acronym=None, ror_id=None, hal_collection=None),
            service=service,
        )
        assert (updated["acronym"], updated["ror_id"], updated["hal_collection"]) == (
            None,
            None,
            None,
        )

    def test_ror_id_full_url_normalized_to_short(self, sa_sync_conn, service):
        """Régression : éditer une structure en envoyant le ROR en URL complète
        (ce que faisait le form admin) ne doit plus stocker l'URL — le service la
        ramène à l'ID court via le VO RorId."""
        row = _create_structure(
            code="X", name="X", structure_type="labo", ror_id="026tc4g97", service=service
        )
        updated = _update_structure(
            row["id"],
            update=StructureUpdate(acronym="X", ror_id="https://ror.org/026tc4g97"),
            service=service,
        )
        assert updated["ror_id"] == "026tc4g97"

    def test_ror_id_invalid_raises(self, sa_sync_conn, service):
        row = _create_structure(code="X", name="X", structure_type="labo", service=service)
        with pytest.raises(ValidationError, match="ror_id invalide"):
            _update_structure(
                row["id"], update=StructureUpdate(ror_id="pas-un-ror"), service=service
            )


class TestDeleteStructure:
    def test_raises_not_found(self, sa_sync_conn, service):
        with pytest.raises(NotFoundError):
            service.delete_structure(999999)

    def test_deletes_existing(self, sa_sync_conn, service):
        row = _create_structure(code="X", name="X", structure_type="labo", service=service)
        service.delete_structure(row["id"])
        result = sa_sync_conn.execute(
            text("SELECT id FROM structures WHERE id = :id"), {"id": row["id"]}
        )
        assert result.first() is None


# ── structure_parents ───────────────────────────────────────────


class TestCreateTutelle:
    def test_creates(self, sa_sync_conn, service):
        parent = _create_structure(
            code="P", name="Parent", structure_type="universite", service=service
        )
        child = _create_structure(code="C", name="Child", structure_type="labo", service=service)
        rel = service.create_tutelle(parent_id=parent["id"], child_id=child["id"])
        assert rel is not None
        assert rel["parent_id"] == parent["id"]
        assert rel["child_id"] == child["id"]

    def test_returns_none_on_conflict(self, sa_sync_conn, service):
        """Si la relation existe déjà, retourne None (ON CONFLICT DO NOTHING)."""
        parent = _create_structure(code="P", name="P", structure_type="universite", service=service)
        child = _create_structure(code="C", name="C", structure_type="labo", service=service)
        service.create_tutelle(parent_id=parent["id"], child_id=child["id"])
        again = service.create_tutelle(parent_id=parent["id"], child_id=child["id"])
        assert again is None

    def test_rejects_self_reference(self, sa_sync_conn, service):
        s = _create_structure(code="S", name="S", structure_type="universite", service=service)
        with pytest.raises(ValidationError, match="Auto-référence"):
            service.create_tutelle(parent_id=s["id"], child_id=s["id"])

    def test_rejects_cycle(self, sa_sync_conn, service):
        """A → B existe ; tenter B → A doit échouer (cycle)."""
        a = _create_structure(code="A", name="A", structure_type="universite", service=service)
        b = _create_structure(code="B", name="B", structure_type="labo", service=service)
        service.create_tutelle(parent_id=a["id"], child_id=b["id"])
        with pytest.raises(ValidationError, match="Cycle"):
            service.create_tutelle(parent_id=b["id"], child_id=a["id"])

    def test_rejects_indirect_cycle(self, sa_sync_conn, service):
        """A → B → C ; tenter C → A doit échouer."""
        a = _create_structure(code="A", name="A", structure_type="universite", service=service)
        b = _create_structure(code="B", name="B", structure_type="labo", service=service)
        c = _create_structure(code="C", name="C", structure_type="equipe", service=service)
        service.create_tutelle(parent_id=a["id"], child_id=b["id"])
        service.create_tutelle(parent_id=b["id"], child_id=c["id"])
        with pytest.raises(ValidationError, match="Cycle"):
            service.create_tutelle(parent_id=c["id"], child_id=a["id"])


class TestDeleteTutelle:
    def test_raises_not_found(self, sa_sync_conn, service):
        with pytest.raises(NotFoundError):
            service.delete_tutelle(999999)

    def test_deletes_existing(self, sa_sync_conn, service):
        parent = _create_structure(code="P", name="P", structure_type="universite", service=service)
        child = _create_structure(code="C", name="C", structure_type="labo", service=service)
        rel = service.create_tutelle(parent_id=parent["id"], child_id=child["id"])
        service.delete_tutelle(rel["id"])
        result = sa_sync_conn.execute(
            text("SELECT id FROM structure_parents WHERE id = :id"), {"id": rel["id"]}
        )
        assert result.first() is None


# ── structure_name_forms ──────────────────────────────────────────


class TestCreateNameForm:
    def test_creates_with_normalization(self, sa_sync_conn, service):
        s = _create_structure(code="X", name="X", structure_type="labo", service=service)
        form = _create_name_form(structure_id=s["id"], form_text="École UCA", service=service)
        # Le form_text est normalisé
        assert form["form_text"] == "ecole uca"
        assert form["is_word_boundary"] is False
        assert form["is_excluding"] is False

    def test_creates_with_context(self, sa_sync_conn, service):
        s = _create_structure(code="X", name="X", structure_type="labo", service=service)
        form = _create_name_form(
            structure_id=s["id"],
            form_text="U999",
            is_word_boundary=True,
            requires_context_of=[s["id"]],
            service=service,
        )
        assert form["is_word_boundary"] is True
        assert form["requires_context_of"] == [s["id"]]

    def test_forces_word_boundary_for_short_form(self, sa_sync_conn, service):
        s = _create_structure(code="X", name="X", structure_type="labo", service=service)
        # Forme normalisée courte (<= 6) : is_word_boundary forcé même non demandé.
        form = _create_name_form(structure_id=s["id"], form_text="INRAE", service=service)
        assert form["form_text"] == "inrae"
        assert form["is_word_boundary"] is True


class TestUpdateNameForm:
    def test_raises_not_found(self, sa_sync_conn, service):
        with pytest.raises(NotFoundError):
            service.update_name_form(999999, update=NameFormUpdate(form_text="x"))

    def test_raises_on_empty_fields(self, sa_sync_conn, service):
        s = _create_structure(code="X", name="X", structure_type="labo", service=service)
        form = _create_name_form(structure_id=s["id"], form_text="x", service=service)
        with pytest.raises(ValidationError):
            service.update_name_form(form["id"], update=NameFormUpdate())

    def test_updates_form_text_with_normalization(self, sa_sync_conn, service):
        s = _create_structure(code="X", name="X", structure_type="labo", service=service)
        form = _create_name_form(structure_id=s["id"], form_text="old", service=service)
        updated = service.update_name_form(form["id"], update=NameFormUpdate(form_text="École NEW"))
        assert updated["form_text"] == "ecole new"

    def test_updates_flags(self, sa_sync_conn, service):
        s = _create_structure(code="X", name="X", structure_type="labo", service=service)
        form = _create_name_form(structure_id=s["id"], form_text="x", service=service)
        updated = service.update_name_form(
            form["id"], update=NameFormUpdate(is_word_boundary=True, is_excluding=True)
        )
        assert updated["is_word_boundary"] is True
        assert updated["is_excluding"] is True

    def test_forces_word_boundary_when_shortened(self, sa_sync_conn, service):
        s = _create_structure(code="X", name="X", structure_type="labo", service=service)
        form = _create_name_form(
            structure_id=s["id"], form_text="Institut Recherche", service=service
        )
        assert form["is_word_boundary"] is False  # forme longue
        updated = service.update_name_form(form["id"], update=NameFormUpdate(form_text="IGCNC"))
        assert updated["is_word_boundary"] is True  # raccourcie → forcé

    def test_forces_word_boundary_on_unchanged_short_form(self, sa_sync_conn, service):
        """Baisser is_word_boundary sans toucher form_text sur une forme courte : re-forcé.

        Le forçage lit le form_text effectif (celui en base si le payload ne le change pas),
        pas seulement le texte fourni ; l'invariant tient sans dépendre de la CHECK DB.
        """
        s = _create_structure(code="X", name="X", structure_type="labo", service=service)
        form = _create_name_form(structure_id=s["id"], form_text="INRAE", service=service)
        assert form["is_word_boundary"] is True  # courte → forcé à la création
        updated = service.update_name_form(
            form["id"], update=NameFormUpdate(is_word_boundary=False)
        )
        assert updated["is_word_boundary"] is True


class TestDeleteNameForm:
    def test_raises_not_found(self, sa_sync_conn, service):
        with pytest.raises(NotFoundError):
            service.delete_name_form(999999)

    def test_deletes_existing(self, sa_sync_conn, service):
        s = _create_structure(code="X", name="X", structure_type="labo", service=service)
        form = _create_name_form(structure_id=s["id"], form_text="x", service=service)
        service.delete_name_form(form["id"])
        result = sa_sync_conn.execute(
            text("SELECT id FROM structure_name_forms WHERE id = :id"), {"id": form["id"]}
        )
        assert result.first() is None
