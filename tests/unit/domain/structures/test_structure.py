"""Tests de l'aggregate root ``Structure`` (scaffolding Phase 1)."""

from domain.structures.name_forms import StructureNameForm
from domain.structures.structure import Structure


class TestStructureConstruction:
    def test_accepts_minimal_args(self):
        s = Structure(id=None, code="UMR-1234", name="Lab", structure_type="laboratoire")
        assert s.id is None
        assert s.code == "UMR-1234"
        assert s.acronym is None
        assert s.ror_id is None
        assert s.name_forms == ()
        assert s.api_ids is None

    def test_accepts_full_args(self):
        nf = StructureNameForm("lab x")
        s = Structure(
            id=1,
            code="UMR-1234",
            name="Lab",
            structure_type="laboratoire",
            acronym="LAB",
            ror_id="0123456",
            rnsr_id="0099999X",
            hal_collection="LAB",
            api_ids={"hal_struct_id": [1, 2]},
            name_forms=(nf,),
        )
        assert s.acronym == "LAB"
        assert s.ror_id == "0123456"
        assert s.api_ids == {"hal_struct_id": [1, 2]}
        assert s.name_forms == (nf,)
