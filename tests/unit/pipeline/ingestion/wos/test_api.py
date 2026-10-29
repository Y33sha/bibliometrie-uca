"""Protocole de l'API WoS : requête Advanced Search, lecture des réponses, DOI interrogeables."""

from __future__ import annotations

import pytest

from pipeline.ingestion.wos.api import (
    build_query,
    filter_doi_for_wos,
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
        # WoS répond 400 à `OG=()` : la requête est refusée avant l'envoi.
        with pytest.raises(ValueError, match="affiliations vide"):
            build_query(year=2024, affiliations=[])


class TestGetRecords:
    def test_extracts_REC_list(self):
        data = {"Data": {"Records": {"records": {"REC": [{"UID": "X"}, {"UID": "Y"}]}}}}
        assert get_records(data) == [{"UID": "X"}, {"UID": "Y"}]

    def test_un_objet_unique_compte_pour_un_enregistrement(self):
        data = {"Data": {"Records": {"records": {"REC": {"UID": "X"}}}}}
        assert get_records(data) == [{"UID": "X"}]

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


class TestFilterDoiForWos:
    # `filter_doi_for_wos` reçoit un DOI normalisé par `clean_doi` et fait seulement le filtrage propre à WoS.

    def test_passes_through_indexed_doi(self):
        assert filter_doi_for_wos("10.1000/abc") == "10.1000/abc"

    def test_filters_zenodo(self):
        # Un préfixe absent de l'index WoS donne None.
        assert filter_doi_for_wos("10.5281/zenodo.123") is None

    def test_filters_arxiv(self):
        assert filter_doi_for_wos("10.48550/arxiv.2401.12345") is None

    def test_filters_ssrn(self):
        assert filter_doi_for_wos("10.2139/ssrn.4567890") is None

    def test_filters_research_square(self):
        assert filter_doi_for_wos("10.21203/rs.3.rs-12345") is None

    def test_filters_doi_with_double_quote(self):
        # Un guillemet casserait la requête WoS `DO=("...")`.
        assert filter_doi_for_wos('10.1000/abc"def') is None

    def test_filters_doi_with_newline(self):
        assert filter_doi_for_wos("10.1000/abc\ndef") is None
