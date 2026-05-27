"""Tests unitaires des méthodes pures de `PgHalExtractAdapter`.

Couvre le savoir adapter sans I/O : construction de requête Solr
(`build_query`), parsing de documents (`extract_id`, `extract_doi`) et
taille de page par collection (`per_page_for`). La plomberie HTTP/SQL
est couverte ailleurs (helper retry + tests d'intégration adapter).
"""

from __future__ import annotations

import pytest

from infrastructure.sources.hal.extract_hal import PgHalExtractAdapter


@pytest.fixture
def adapter() -> PgHalExtractAdapter:
    return PgHalExtractAdapter(base_url="https://example/")


class TestBuildQuery:
    def test_since_takes_precedence_over_years(self, adapter):
        # `since` est fourni : on filtre par submittedDate_tdate, sans toucher aux années.
        assert (
            adapter.build_query(years=[2024], since="2026-05-01")
            == "submittedDate_tdate:[2026-05-01T00:00:00Z TO *]"
        )

    def test_since_alone(self, adapter):
        assert adapter.build_query(years=None, since="2025-12-31") == (
            "submittedDate_tdate:[2025-12-31T00:00:00Z TO *]"
        )

    def test_years_single(self, adapter):
        assert adapter.build_query(years=[2024]) == "producedDateY_i:[2024 TO 2024]"

    def test_years_range_uses_min_and_max(self, adapter):
        # L'ordre n'importe pas : min/max recalculent l'intervalle.
        assert adapter.build_query(years=[2023, 2026, 2024]) == "producedDateY_i:[2023 TO 2026]"

    def test_raises_when_no_filter(self, adapter):
        with pytest.raises(ValueError):
            adapter.build_query(years=None)

    def test_raises_on_empty_years(self, adapter):
        with pytest.raises(ValueError):
            adapter.build_query(years=[])


class TestExtractId:
    def test_returns_field_value(self, adapter):
        assert adapter.extract_id({"halId_s": "hal-12345"}) == "hal-12345"

    def test_returns_empty_string_when_missing(self, adapter):
        assert adapter.extract_id({}) == ""


class TestExtractDoi:
    def test_returns_cleaned_doi(self, adapter):
        # `clean_doi` retire un éventuel préfixe URL.
        assert adapter.extract_doi({"doiId_s": "https://doi.org/10.1000/abc"}) == "10.1000/abc"

    def test_returns_bare_doi(self, adapter):
        assert adapter.extract_doi({"doiId_s": "10.1000/abc"}) == "10.1000/abc"

    def test_returns_none_when_missing(self, adapter):
        assert adapter.extract_doi({}) is None

    def test_returns_none_when_blank(self, adapter):
        assert adapter.extract_doi({"doiId_s": ""}) is None


class TestPerPageFor:
    def test_default_per_page(self, adapter):
        assert adapter.per_page_for(None) == 500
        assert adapter.per_page_for("UNKNOWN-COLL") == 500

    def test_override_for_megaauthorship_collection(self, adapter):
        # LPC-CLERMONT : physique des particules, payloads label_xml énormes → per_page réduit.
        assert adapter.per_page_for("LPC-CLERMONT") == 50
