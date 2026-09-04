"""Tests unitaires du pilotage de l'extraction HAL par `HalExtractor`.

La pagination `cursorMark` d'`extract_union` est éprouvée à part. Ce module porte sur ce qui l'entoure : découpage du travail en périmètres temporels, mode incrémental par date de dépôt, refus d'une configuration sans collection, arrêt sur circuit-breaker.

Pas de réseau ni de base : un faux `HalExtractAdapter` sert une page vide, et la connexion est un mock.
"""

from __future__ import annotations

import argparse
import logging
from unittest.mock import MagicMock

import pytest

from application.pipeline.extract.base import ExtractionConfigError
from application.pipeline.extract.extract_hal import HalExtractor
from application.ports.pipeline.extract.hal import HalExtractConfig

_LOGGER = logging.getLogger("test")

# Page Solr close : aucun document, marqueur inchangé — la pagination s'arrête au premier tour.
_PAGE_VIDE = {"response": {"numFound": 0, "docs": []}, "nextCursorMark": "*"}


def _adapter(collections: dict[str, str], annees: list[int]) -> MagicMock:
    a = MagicMock()
    a.load_config.return_value = HalExtractConfig(
        base_url="https://example/",
        all_collections=dict(collections),
        n_collections=len(collections),
    )
    a.get_years.return_value = annees
    a.build_query.return_value = "q"
    a.build_collections_fq.return_value = "collCode_s:(…)"
    a.fetch_page_cursor.return_value = _PAGE_VIDE
    return a


def _args(**surcharges) -> argparse.Namespace:
    valeurs: dict = {"dry_run": False, "year": None, "start_year": None, "since": None}
    valeurs.update(surcharges)
    return argparse.Namespace(**valeurs)


def test_une_passe_par_annee_de_la_configuration():
    adapter = _adapter({"C": "Coll"}, [2023, 2024])
    HalExtractor(MagicMock(), _LOGGER, adapter).run(_args())
    annees_demandees = [appel.kwargs.get("years") for appel in adapter.build_query.call_args_list]
    assert annees_demandees == [[2023], [2024]]


def test_une_annee_demandee_ignore_la_configuration():
    adapter = _adapter({"C": "Coll"}, [2020, 2021])
    HalExtractor(MagicMock(), _LOGGER, adapter).run(_args(year=2024))
    assert adapter.build_query.call_args.kwargs.get("years") == [2024]


def test_mode_incremental_fait_une_seule_passe_sur_la_date():
    adapter = _adapter({"C": "Coll"}, [2020, 2021, 2022])
    HalExtractor(MagicMock(), _LOGGER, adapter).run(_args(since="2026-01-01"))
    assert adapter.fetch_page_cursor.call_count == 1
    assert adapter.build_query.call_args.kwargs.get("since") == "2026-01-01"


def test_dry_run_ne_journalise_pas_de_bilan_d_annee():
    adapter = _adapter({"C": "Coll"}, [2024])
    metrics = HalExtractor(MagicMock(), _LOGGER, adapter).run(_args(dry_run=True))
    assert metrics.total == 0


def test_sans_collection_refuse():
    adapter = _adapter({}, [2024])
    with pytest.raises(ExtractionConfigError, match="aucune collection HAL"):
        HalExtractor(MagicMock(), _LOGGER, adapter).run(_args())


def test_s_arrete_quand_la_source_est_a_bout():
    adapter = _adapter({"C": "Coll"}, [2023, 2024])
    breaker = MagicMock()
    breaker.tripped = True
    metrics = HalExtractor(MagicMock(), _LOGGER, adapter).run(_args(), breaker=breaker)
    assert metrics.total == 0
    adapter.fetch_page_cursor.assert_not_called()
