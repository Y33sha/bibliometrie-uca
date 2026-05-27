"""Tests des heuristiques d'orchestration HAL (`application/pipeline/extract/hal_helpers.py`).

Couvre la décision d'aiguillage full-fetch / incrémental
(`choose_extraction_mode`, `count_full_fetch_pages`). Pas d'I/O, pas de
format HAL : `per_page` est passé en paramètre.
"""

from __future__ import annotations

from application.pipeline.extract.hal_helpers import (
    choose_extraction_mode,
    count_full_fetch_pages,
)


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

    def test_pres_clermont_umbrella_chooses_incremental(self):
        # Cas typique umbrella (PRES_CLERMONT) : 19 orphelins, 12 pages full.
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
