"""Tests du modèle JSONB infrastructure/jsonb_models/structure.py."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from infrastructure.jsonb_models.structure import StructureApiIds


class TestStructureApiIds:
    def test_empty(self):
        s = StructureApiIds()
        assert s.to_dict() == {}

    def test_single_source(self):
        s = StructureApiIds(openalex=["I123456789"])
        assert s.openalex == ["I123456789"]
        assert s.to_dict() == {"openalex": ["I123456789"]}

    def test_multi_source(self):
        s = StructureApiIds(
            openalex=["I123456789", "I987654321"],
            wos=["org-1234"],
            scanr=["123456789"],
            theses=["252404955"],
        )
        d = s.to_dict()
        assert d["openalex"] == ["I123456789", "I987654321"]
        assert d["wos"] == ["org-1234"]

    def test_string_coerced_to_list(self):
        """Données historiques : un scalaire passé au lieu d'une liste
        est wrappé automatiquement."""
        s = StructureApiIds(openalex="I123456789")
        assert s.openalex == ["I123456789"]

    def test_empty_string_becomes_none(self):
        s = StructureApiIds(wos="")
        assert s.wos is None

    def test_empty_lists_omitted_from_dict(self):
        """to_dict compact : les listes vides sont éliminées."""
        s = StructureApiIds(openalex=["I123"], wos=[])
        d = s.to_dict()
        assert "openalex" in d
        assert "wos" not in d

    def test_rejects_unknown_source(self):
        """Clés strictes : une source hors whitelist est rejetée
        (la liste des sources `api_ids` est connaissance métier centralisée
        dans `domain.sources.STRUCTURE_API_SOURCES`)."""
        with pytest.raises(PydanticValidationError):
            StructureApiIds(openalex=["I123"], crossref=["10.5281/..."])

    def test_fields_match_domain_whitelist(self):
        """Les champs déclarés du modèle doivent correspondre exactement
        à la whitelist `domain.sources.STRUCTURE_API_SOURCES_SET`."""
        from domain.sources.registry import STRUCTURE_API_SOURCES_SET

        assert set(StructureApiIds.model_fields.keys()) == STRUCTURE_API_SOURCES_SET

    def test_rejects_non_string_in_list(self):
        """Les valeurs d'une liste doivent être des strings."""
        with pytest.raises(PydanticValidationError):
            StructureApiIds(openalex=[123, 456])

    def test_roundtrip_from_db(self):
        from_db = {
            "openalex": ["I123456789"],
            "wos": ["org-1234", "org-5678"],
            "theses": ["252404955"],
        }
        s = StructureApiIds(**from_db)
        back = s.to_dict()
        assert back == from_db
