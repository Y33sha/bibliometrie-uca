"""Requête et champs de l'API WoS (`pipeline.ingestion.wos.fields`)."""

from __future__ import annotations

import pytest

from pipeline.ingestion.wos.fields import extract_doi, extract_ut


class TestExtractUt:
    def test_returns_uid_field(self):
        assert extract_ut({"UID": "WOS:000819841500009"}) == "WOS:000819841500009"

    def test_raises_when_missing(self):
        # `UID` est censé être toujours présent dans une réponse WoS — toute
        # absence est anormale et doit remonter (pas de fallback silencieux).
        with pytest.raises(KeyError):
            extract_ut({})


class TestExtractDoi:
    def test_ligne_d_export(self):
        assert extract_doi({"UT": "WOS:1", "DI": "10.1000/ABC"}) == "10.1000/abc"
        assert extract_doi({"UT": "WOS:1"}) is None

    def test_finds_doi_in_identifier_list(self):
        rec = {
            "dynamic_data": {
                "cluster_related": {
                    "identifiers": {
                        "identifier": [
                            {"type": "issn", "value": "1234-5678"},
                            {"type": "doi", "value": "10.1000/abc"},
                        ]
                    }
                }
            }
        }
        assert extract_doi(rec) == "10.1000/abc"

    def test_handles_single_identifier_as_dict(self):
        # WoS retourne tantôt une liste, tantôt un dict unique quand il n'y
        # a qu'un seul identifiant. `extract_doi` doit gérer les deux.
        rec = {
            "dynamic_data": {
                "cluster_related": {
                    "identifiers": {"identifier": {"type": "doi", "value": "10.1000/abc"}}
                }
            }
        }
        assert extract_doi(rec) == "10.1000/abc"

    def test_normalizes_value_via_clean_doi(self):
        # Le DOI extrait passe par `clean_doi` : préfixe URL, casse et espaces
        # sont normalisés à la source (forme canonique unique).
        rec = {
            "dynamic_data": {
                "cluster_related": {
                    "identifiers": {
                        "identifier": [{"type": "doi", "value": "  https://doi.org/10.1000/ABC  "}]
                    }
                }
            }
        }
        assert extract_doi(rec) == "10.1000/abc"

    def test_returns_none_when_no_doi_type(self):
        rec = {
            "dynamic_data": {
                "cluster_related": {"identifiers": {"identifier": [{"type": "issn", "value": "X"}]}}
            }
        }
        assert extract_doi(rec) is None

    def test_returns_none_on_missing_levels(self):
        # Chaque niveau peut manquer : on doit tomber sur None proprement.
        assert extract_doi({}) is None
        assert extract_doi({"dynamic_data": {}}) is None
        assert extract_doi({"dynamic_data": {"cluster_related": {}}}) is None
        assert extract_doi({"dynamic_data": {"cluster_related": {"identifiers": {}}}}) is None

    def test_returns_none_when_identifier_value_is_none(self):
        rec = {
            "dynamic_data": {
                "cluster_related": {"identifiers": {"identifier": [{"type": "doi", "value": None}]}}
            }
        }
        assert extract_doi(rec) is None

    def test_returns_none_when_identifier_unexpected_shape(self):
        # `identifier` n'est ni dict ni list → retour silencieux à None.
        rec = {
            "dynamic_data": {
                "cluster_related": {"identifiers": {"identifier": "not-a-list-nor-dict"}}
            }
        }
        assert extract_doi(rec) is None
