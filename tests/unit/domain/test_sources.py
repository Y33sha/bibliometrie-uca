"""Tests des constantes et helpers de `domain/sources.py` — registre
des sources et ordres de priorité."""

import pytest

from domain.errors import ValidationError
from domain.sources.registry import (
    ALL_SOURCES,
    DOI_SEARCHABLE_SOURCES,
    SOURCE_PRIORITY,
    require_known_source,
    source_record_url,
)


class TestRequireKnownSource:
    def test_known_source_passes(self):
        require_known_source("hal")

    def test_unknown_source_is_named(self):
        with pytest.raises(ValidationError, match="Source inconnue : 'inconnue'"):
            require_known_source("inconnue")


class TestSourcePriority:
    def test_theses_first(self):
        assert SOURCE_PRIORITY[0] == "theses"

    def test_wos_last(self):
        assert SOURCE_PRIORITY[-1] == "wos"

    def test_contains_all_sources(self):
        assert set(SOURCE_PRIORITY) == set(ALL_SOURCES)


class TestDoiSearchableSources:
    def test_excludes_theses(self):
        """theses.fr ne se requête pas par DOI mais par NNT — exclue du pool DOI-driven."""
        assert "theses" not in DOI_SEARCHABLE_SOURCES

    def test_contains_all_doi_searchable(self):
        assert set(DOI_SEARCHABLE_SOURCES) == {
            "hal",
            "openalex",
            "wos",
            "scanr",
            "crossref",
            "datacite",
        }


class TestSourceRecordUrl:
    def test_depot_hal(self):
        assert source_record_url("hal", "hal-04579115") == "https://hal.science/hal-04579115"

    def test_depot_dumas(self):
        assert (
            source_record_url("hal", "dumas-12345678")
            == "https://dumas.ccsd.cnrs.fr/dumas-12345678"
        )

    def test_these_hal_ouverte(self):
        assert source_record_url("hal", "tel-04579115", "green") == (
            "https://theses.hal.science/tel-04579115"
        )

    def test_these_hal_fermee(self):
        assert source_record_url("hal", "tel-04579115", "closed") == (
            "https://hal.science/tel-04579115"
        )

    def test_identifiant_scanr_encode_en_entier(self):
        assert source_record_url("scanr", "doi/10.1234/test") == (
            "https://scanr.enseignementsup-recherche.gouv.fr/publications/doi%2F10.1234%2Ftest"
        )

    def test_crossref_et_datacite_par_doi(self):
        assert source_record_url("crossref", "10.1111/jpm.70007") == (
            "https://doi.org/10.1111/jpm.70007"
        )
        assert source_record_url("datacite", "10.5281/zenodo.123") == (
            "https://doi.org/10.5281/zenodo.123"
        )

    def test_identifiant_encode(self):
        assert source_record_url("hal", "hal-1?x=@evil.org#") == (
            "https://hal.science/hal-1%3Fx%3D%40evil.org%23"
        )

    def test_source_inconnue(self):
        with pytest.raises(ValueError):
            source_record_url("inconnue", "x")
