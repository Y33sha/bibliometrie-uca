"""Tests unitaires de `domain/sources/wos_extract.py`."""

from __future__ import annotations

import pytest

from domain.sources.wos_extract import (
    build_query,
    clean_doi_for_wos,
    extract_doi,
    extract_ut,
    get_records,
    get_records_found,
)


class TestBuildQuery:
    def test_single_org(self):
        assert build_query(year=2024, affiliations=["UCA"]) == "OG=(UCA) AND PY=(2024)"

    def test_multi_orgs_joined_with_or(self):
        assert build_query(year=2024, affiliations=["UCA", "CHU", "INP"]) == (
            "OG=(UCA OR CHU OR INP) AND PY=(2024)"
        )

    def test_empty_affiliations_raises(self):
        # `OG=()` côté WoS renvoie 400 Bad Request — on échoue tôt côté client
        # plutôt que d'envoyer une requête qu'on sait inutile.
        with pytest.raises(ValueError, match="affiliations vide"):
            build_query(year=2024, affiliations=[])


class TestExtractUt:
    def test_returns_uid_field(self):
        assert extract_ut({"UID": "WOS:000819841500009"}) == "WOS:000819841500009"

    def test_raises_when_missing(self):
        # `UID` est censé être toujours présent dans une réponse WoS — toute
        # absence est anormale et doit remonter (pas de fallback silencieux).
        with pytest.raises(KeyError):
            extract_ut({})


class TestExtractDoi:
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

    def test_strips_whitespace_from_value(self):
        rec = {
            "dynamic_data": {
                "cluster_related": {
                    "identifiers": {"identifier": [{"type": "doi", "value": "  10.1000/abc  "}]}
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


class TestGetRecords:
    def test_extracts_REC_list(self):
        data = {"Data": {"Records": {"records": {"REC": [{"UID": "X"}, {"UID": "Y"}]}}}}
        assert get_records(data) == [{"UID": "X"}, {"UID": "Y"}]

    def test_returns_empty_on_missing_path(self):
        assert get_records({}) == []
        assert get_records({"Data": {}}) == []
        assert get_records({"Data": {"Records": {}}}) == []
        assert get_records({"Data": {"Records": {"records": {}}}}) == []


class TestGetRecordsFound:
    def test_returns_count(self):
        assert get_records_found({"QueryResult": {"RecordsFound": 42}}) == 42

    def test_returns_zero_on_missing(self):
        assert get_records_found({}) == 0
        assert get_records_found({"QueryResult": {}}) == 0


class TestCleanDoiForWos:
    def test_passes_through_clean_doi(self):
        assert clean_doi_for_wos("10.1000/abc") == "10.1000/abc"

    def test_strips_url_params(self):
        # DOI tronqué après `?` ou `&` (paramètres résiduels d'URL).
        assert clean_doi_for_wos("10.1000/abc?foo=1") == "10.1000/abc"
        assert clean_doi_for_wos("10.1000/abc&bar=2") == "10.1000/abc"

    def test_strips_whitespace(self):
        assert clean_doi_for_wos("  10.1000/abc  ") == "10.1000/abc"

    def test_filters_zenodo(self):
        # Préfixes WoS-unindexed → None pour éviter l'appel inutile.
        assert clean_doi_for_wos("10.5281/zenodo.123") is None

    def test_filters_arxiv(self):
        assert clean_doi_for_wos("10.48550/arXiv.2401.12345") is None

    def test_filters_ssrn(self):
        assert clean_doi_for_wos("10.2139/ssrn.4567890") is None

    def test_filters_research_square(self):
        assert clean_doi_for_wos("10.21203/rs.3.rs-12345") is None

    def test_filter_is_case_insensitive(self):
        # Le prefix matching utilise `.lower()` : un DOI en majuscule reste filtré.
        assert clean_doi_for_wos("10.5281/Zenodo.123") is None

    def test_filters_doi_with_double_quote(self):
        # `"` casserait la requête WoS `DO=("...")` côté backend.
        assert clean_doi_for_wos('10.1000/abc"def') is None

    def test_filters_doi_with_newline(self):
        assert clean_doi_for_wos("10.1000/abc\ndef") is None
