"""Tests du modèle Pydantic PersonSourceIds (colonne JSONB
``source_persons.source_ids``)."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from infrastructure.db.jsonb_models.persons import PersonSourceIds


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
