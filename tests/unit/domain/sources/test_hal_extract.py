"""Tests unitaires de `domain/sources/hal_extract.py`.

Couvre les pure functions du module HAL (build_query, extract_hal_id,
extract_doi) et la décision d'aiguillage full-fetch / incrémental
(choose_extraction_mode, count_full_fetch_pages).

`build_url` est un helper infra (formatage d'URL Solr HAL) et reste
dans `infrastructure/sources/hal/extract_hal.py`.
"""

from __future__ import annotations

import pytest

from domain.sources.hal_extract import (
    build_query,
    choose_extraction_mode,
    count_full_fetch_pages,
    extract_doi,
    extract_hal_id,
)


class TestBuildQuery:
    def test_since_takes_precedence_over_years(self):
        # `since` est fourni : on filtre par submittedDate_tdate, sans toucher aux années.
        assert (
            build_query(years=[2024], since="2026-05-01")
            == "submittedDate_tdate:[2026-05-01T00:00:00Z TO *]"
        )

    def test_since_alone(self):
        assert build_query(years=None, since="2025-12-31") == (
            "submittedDate_tdate:[2025-12-31T00:00:00Z TO *]"
        )

    def test_years_single(self):
        assert build_query(years=[2024]) == "producedDateY_i:[2024 TO 2024]"

    def test_years_range_uses_min_and_max(self):
        # L'ordre n'importe pas : min/max recalculent l'intervalle.
        assert build_query(years=[2023, 2026, 2024]) == "producedDateY_i:[2023 TO 2026]"

    def test_raises_when_no_filter(self):
        with pytest.raises(ValueError):
            build_query(years=None)

    def test_raises_on_empty_years(self):
        with pytest.raises(ValueError):
            build_query(years=[])


class TestExtractHalId:
    def test_returns_field_value(self):
        assert extract_hal_id({"halId_s": "hal-12345"}) == "hal-12345"

    def test_returns_empty_string_when_missing(self):
        assert extract_hal_id({}) == ""


class TestExtractDoi:
    def test_returns_cleaned_doi(self):
        # `clean_doi` retire un éventuel préfixe URL.
        assert extract_doi({"doiId_s": "https://doi.org/10.1000/abc"}) == "10.1000/abc"

    def test_returns_bare_doi(self):
        assert extract_doi({"doiId_s": "10.1000/abc"}) == "10.1000/abc"

    def test_returns_none_when_missing(self):
        assert extract_doi({}) is None

    def test_returns_none_when_blank(self):
        assert extract_doi({"doiId_s": ""}) is None


class TestCountFullFetchPages:
    def test_zero_total(self):
        assert count_full_fetch_pages(total_count=0, per_page=500) == 0

    def test_negative_total_clamps_to_zero(self):
        # Guard défensif : ne pas exploser sur une valeur incohérente.
        assert count_full_fetch_pages(total_count=-1, per_page=500) == 0

    def test_exact_multiple(self):
        assert count_full_fetch_pages(total_count=1000, per_page=500) == 2

    def test_ceil_division(self):
        # 501 docs à 500 par page = 2 pages (501/500 → 2 plein).
        assert count_full_fetch_pages(total_count=501, per_page=500) == 2

    def test_single_partial_page(self):
        assert count_full_fetch_pages(total_count=42, per_page=500) == 1


class TestChooseExtractionMode:
    def test_empty_collection_is_skip(self):
        assert choose_extraction_mode(total_count=0, n_orphans=0, per_page=500) == "skip"

    def test_zero_orphans_chooses_incremental(self):
        # Aucun nouveau doc à fetcher : on tague juste les connus, jamais de full-fetch.
        assert choose_extraction_mode(total_count=6000, n_orphans=0, per_page=500) == "incremental"

    def test_orphans_below_pages_chooses_incremental(self):
        # 5 orphelins vs 12 pages → 5 fetchs individuels.
        assert choose_extraction_mode(total_count=6000, n_orphans=5, per_page=500) == "incremental"

    def test_orphans_at_threshold_chooses_full(self):
        # Inégalité stricte `n_orphans < 10 * full_fetch_pages` : à égalité, on bascule en full.
        # 12 pages × ratio 10 = 120 orphelins seuil → 120 = full.
        assert choose_extraction_mode(total_count=6000, n_orphans=120, per_page=500) == "full"

    def test_orphans_just_below_threshold_chooses_incremental(self):
        # 12 pages × 10 = 120 ; 119 orphelins → incremental.
        assert (
            choose_extraction_mode(total_count=6000, n_orphans=119, per_page=500) == "incremental"
        )

    def test_orphans_far_above_threshold_chooses_full(self):
        # Beaucoup d'orphelins (collection essentiellement nouvelle) : full reste optimal.
        assert choose_extraction_mode(total_count=6000, n_orphans=5000, per_page=500) == "full"

    def test_pres_uca_umbrella_chooses_incremental(self):
        # Cas typique umbrella (PRES_UCA / PRES_CLERMONT) : 19 orphelins, 12 pages full.
        # 19 < 10 × 12 = 120 → incremental. Avec l'ancien ratio 1:1, choisissait `full`
        # (catastrophique car HAL_FIELDS inclut label_xml × 500 docs/page).
        assert choose_extraction_mode(total_count=6000, n_orphans=19, per_page=500) == "incremental"

    def test_small_collection_few_orphans_chooses_incremental(self):
        # Mini-collection : 42 docs en 1 page, 5 orphelins. Seuil = 1 × 10 = 10 → 5 < 10
        # → incremental (1 page de 500 ≈ 10 fetchs unitaires, donc 5 unitaires < 1 page).
        assert choose_extraction_mode(total_count=42, n_orphans=5, per_page=500) == "incremental"

    def test_small_collection_many_orphans_chooses_full(self):
        # Mini-collection avec beaucoup d'orphelins : 42 docs en 1 page, 15 orphelins.
        # 15 > 10 → full (autant tirer une page).
        assert choose_extraction_mode(total_count=42, n_orphans=15, per_page=500) == "full"
