"""Tests de l'aggregate root ``Structure``."""

import pytest

from domain.errors import ValidationError
from domain.structures.identifiers import HalCollection, RorId
from domain.structures.name_forms import StructureNameForm
from domain.structures.structure import Structure, StructureType


class TestStructureConstruction:
    def test_accepts_minimal_args(self):
        s = Structure(
            id=None,
            code="UMR-1234",
            name="Lab",
            structure_type=StructureType.LABO,
        )
        assert s.id is None
        assert s.code == "UMR-1234"
        assert s.acronym is None
        assert s.ror_id is None
        assert s.hal_collection is None
        assert s.name_forms == ()
        assert s.api_ids is None

    def test_accepts_full_args(self):
        nf = StructureNameForm("lab x")
        s = Structure(
            id=1,
            code="UMR-1234",
            name="Lab",
            structure_type=StructureType.LABO,
            acronym="LAB",
            ror_id=RorId("02feahw73"),
            hal_collection=HalCollection("LIMOS"),
            api_ids={"hal_struct_id": ["1", "2"]},
            name_forms=(nf,),
        )
        assert s.acronym == "LAB"
        assert s.ror_id == RorId("02feahw73")
        assert s.hal_collection == HalCollection("LIMOS")
        assert s.api_ids == {"hal_struct_id": ["1", "2"]}
        assert s.name_forms == (nf,)


class TestRorId:
    def test_accepts_short_form(self):
        assert RorId("02feahw73").value == "02feahw73"

    def test_accepts_url_form(self):
        assert RorId("https://ror.org/02feahw73").value == "02feahw73"
        assert RorId("http://ror.org/02feahw73").value == "02feahw73"
        assert RorId("ror.org/02feahw73").value == "02feahw73"

    def test_normalizes_case(self):
        assert RorId("02FEAHW73").value == "02feahw73"

    def test_rejects_invalid_alphabet(self):
        # ROR alphabet exclut i/l/o/u
        with pytest.raises(ValidationError):
            RorId("02feai073")  # 'i' interdit
        with pytest.raises(ValidationError):
            RorId("02feal073")  # 'l' interdit

    def test_rejects_wrong_length(self):
        with pytest.raises(ValidationError):
            RorId("02feahw7")  # 8 chars
        with pytest.raises(ValidationError):
            RorId("02feahw733")  # 10 chars

    def test_rejects_wrong_prefix(self):
        # Tous les ROR commencent par '0' (jusqu'à présent)
        with pytest.raises(ValidationError):
            RorId("12feahw73")

    def test_try_parse_returns_none_on_invalid(self):
        assert RorId.try_parse(None) is None
        assert RorId.try_parse("") is None
        assert RorId.try_parse("garbage") is None
        assert RorId.try_parse("02feahw73").value == "02feahw73"

    def test_str_returns_canonical(self):
        assert str(RorId("https://ror.org/02feahw73")) == "02feahw73"


class TestHalCollection:
    def test_accepts_simple_code(self):
        assert HalCollection("LIMOS").value == "LIMOS"

    def test_accepts_underscore(self):
        assert HalCollection("INSTITUT_PASCAL").value == "INSTITUT_PASCAL"

    def test_accepts_hyphen(self):
        assert HalCollection("LPC-CLERMONT").value == "LPC-CLERMONT"

    def test_normalizes_case_and_whitespace(self):
        assert HalCollection("  limos  ").value == "LIMOS"

    def test_rejects_empty(self):
        with pytest.raises(ValidationError):
            HalCollection("")
        with pytest.raises(ValidationError):
            HalCollection("   ")

    def test_rejects_invalid_chars(self):
        with pytest.raises(ValidationError):
            HalCollection("LAB X")  # espace interne
        with pytest.raises(ValidationError):
            HalCollection("LABO.X")  # point
        with pytest.raises(ValidationError):
            HalCollection("ÉCOLE")  # accent

    def test_try_parse_returns_none_on_invalid(self):
        assert HalCollection.try_parse(None) is None
        assert HalCollection.try_parse("") is None
        assert HalCollection.try_parse("LAB X") is None
        assert HalCollection.try_parse("LIMOS").value == "LIMOS"
