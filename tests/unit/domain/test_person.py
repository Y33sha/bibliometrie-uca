"""Tests des value objects de domain/person.py (ORCID, IdHAL, IdRef)
et des modèles JSONB (PersonSourceIds)."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from domain.errors import ConflictError, ValidationError
from domain.person import ORCID, IdHAL, IdRef, PersonSourceIds, check_can_merge_persons

# ── ORCID ──────────────────────────────────────────────────────────


class TestORCIDConstruction:
    def test_accepts_canonical_form(self):
        o = ORCID("0000-0001-2345-6789")
        assert o.value == "0000-0001-2345-6789"

    def test_accepts_with_checksum_X(self):
        o = ORCID("0000-0001-2345-678X")
        assert o.value == "0000-0001-2345-678X"

    def test_lowercases_x_to_uppercase(self):
        assert ORCID("0000-0001-2345-678x").value == "0000-0001-2345-678X"

    def test_strips_https_prefix(self):
        assert ORCID("https://orcid.org/0000-0001-2345-6789").value == "0000-0001-2345-6789"

    def test_strips_http_prefix(self):
        assert ORCID("http://orcid.org/0000-0001-2345-6789").value == "0000-0001-2345-6789"

    def test_strips_bare_orcid_org_prefix(self):
        assert ORCID("orcid.org/0000-0001-2345-6789").value == "0000-0001-2345-6789"

    def test_adds_hyphens_if_missing(self):
        assert ORCID("0000000123456789").value == "0000-0001-2345-6789"


class TestORCIDInvalid:
    def test_raises_on_empty(self):
        with pytest.raises(ValidationError):
            ORCID("")

    def test_raises_on_too_short(self):
        with pytest.raises(ValidationError):
            ORCID("0000-0001-2345")

    def test_raises_on_non_numeric_body(self):
        with pytest.raises(ValidationError):
            ORCID("0000-000A-2345-6789")

    def test_raises_on_wrong_shape(self):
        with pytest.raises(ValidationError):
            ORCID("garbage")


class TestORCIDTryParse:
    def test_none(self):
        assert ORCID.try_parse(None) is None

    def test_invalid(self):
        assert ORCID.try_parse("not an orcid") is None

    def test_valid(self):
        assert ORCID.try_parse("0000-0001-2345-6789") is not None


# ── IdHAL ──────────────────────────────────────────────────────────


class TestIdHALConstruction:
    def test_accepts_slug(self):
        assert IdHAL("jean-dupont").value == "jean-dupont"

    def test_accepts_short_slug(self):
        assert IdHAL("jdupont").value == "jdupont"

    def test_accepts_numeric_legacy(self):
        """Les anciens comptes HAL ont des IdHAL numériques (idHal_i)."""
        assert IdHAL("123456").value == "123456"

    def test_lowercases(self):
        assert IdHAL("Jean-Dupont").value == "jean-dupont"

    def test_strips_whitespace(self):
        assert IdHAL("  jean-dupont  ").value == "jean-dupont"


class TestIdHALInvalid:
    def test_raises_on_empty(self):
        with pytest.raises(ValidationError):
            IdHAL("")

    def test_raises_on_too_short(self):
        with pytest.raises(ValidationError):
            IdHAL("j")

    def test_raises_on_leading_hyphen(self):
        with pytest.raises(ValidationError):
            IdHAL("-jean-dupont")

    def test_raises_on_underscore(self):
        with pytest.raises(ValidationError):
            IdHAL("jean_dupont")

    def test_raises_on_special_chars(self):
        with pytest.raises(ValidationError):
            IdHAL("jean.dupont")


class TestIdHALTryParse:
    def test_none(self):
        assert IdHAL.try_parse(None) is None

    def test_invalid(self):
        assert IdHAL.try_parse("j") is None

    def test_valid(self):
        assert IdHAL.try_parse("jean-dupont") is not None


# ── IdRef ──────────────────────────────────────────────────────────


class TestIdRefConstruction:
    def test_accepts_canonical_ppn(self):
        assert IdRef("252404955").value == "252404955"

    def test_accepts_ppn_with_X(self):
        assert IdRef("05547854X").value == "05547854X"

    def test_lowercases_x_to_uppercase(self):
        assert IdRef("05547854x").value == "05547854X"

    def test_strips_idref_url(self):
        assert IdRef("https://www.idref.fr/252404955/id").value == "252404955"
        assert IdRef("idref.fr/252404955").value == "252404955"


class TestIdRefInvalid:
    def test_raises_on_empty(self):
        with pytest.raises(ValidationError):
            IdRef("")

    def test_raises_on_too_short(self):
        with pytest.raises(ValidationError):
            IdRef("12345678")  # 8 chiffres, il manque la clé

    def test_raises_on_too_long(self):
        with pytest.raises(ValidationError):
            IdRef("1234567890")

    def test_raises_on_letters_in_body(self):
        with pytest.raises(ValidationError):
            IdRef("12A456789")


# ── PersonSourceIds ────────────────────────────────────────────────


class TestPersonSourceIds:
    def test_empty(self):
        s = PersonSourceIds()
        assert s.hal_person_id is None
        assert s.idhal is None
        assert s.hal_form_id is None
        assert s.to_dict() == {}

    def test_hal_full(self):
        s = PersonSourceIds(hal_person_id=900001, idhal="jean-dupont", hal_form_id=123456)
        assert s.hal_person_id == 900001
        assert s.idhal == "jean-dupont"
        assert s.hal_form_id == 123456

    def test_idhal_normalization(self):
        """idhal est normalisé via le VO IdHAL (lowercase, trim)."""
        s = PersonSourceIds(idhal="  Jean-Dupont  ")
        assert s.idhal == "jean-dupont"

    def test_idhal_invalid_raises(self):
        with pytest.raises(PydanticValidationError):
            PersonSourceIds(idhal="jean.dupont")  # point interdit

    def test_idhal_empty_treated_as_none(self):
        s = PersonSourceIds(idhal="")
        assert s.idhal is None

    def test_to_dict_omits_none(self):
        """Un dict compact côté BD, sans valeurs null superflues."""
        s = PersonSourceIds(idhal="jdupont")
        assert s.to_dict() == {"idhal": "jdupont"}

    def test_accepts_extra_keys(self):
        """Ouvert aux évolutions (autre source introduirait une nouvelle clé)."""
        s = PersonSourceIds(idhal="jdupont", scanr_id="P-123", wos_researcher_id="A-9999")
        d = s.to_dict()
        assert d["scanr_id"] == "P-123"
        assert d["wos_researcher_id"] == "A-9999"

    def test_hal_person_id_as_int(self):
        """hal_person_id doit être int, pas string."""
        with pytest.raises(PydanticValidationError):
            PersonSourceIds(hal_person_id="not-an-int")

    def test_roundtrip_from_db(self):
        from_db = {"hal_person_id": 900001, "idhal": "jean-dupont", "hal_form_id": 555}
        s = PersonSourceIds(**from_db)
        back = s.to_dict()
        assert back == from_db


# ── Règle métier de fusion ─────────────────────────────────────────


class TestCheckCanMergePersons:
    def test_allows_merge_when_no_distinct_rh(self):
        # Ne lève pas : retour implicite None
        assert check_can_merge_persons(False, 1, 2) is None

    def test_raises_when_distinct_rh(self):
        with pytest.raises(ConflictError, match="REFUS de fusion"):
            check_can_merge_persons(True, 1, 2)

    def test_error_message_contains_both_ids(self):
        with pytest.raises(ConflictError, match="#42.*#17"):
            check_can_merge_persons(True, 42, 17)

    def test_error_message_mentions_rh(self):
        with pytest.raises(ConflictError, match="fiche RH distincte"):
            check_can_merge_persons(True, 1, 2)
