"""Tests unitaires de l'orchestrateur d'extraction OpenAlex.

Pas de réseau ni de base : un faux `OpenalexExtractAdapter` sert des pages scriptées, et la connexion est un mock dont seul `commit` est appelé. Ce qui est éprouvé ici est le pilotage — pagination par curseur jusqu'à son épuisement, cumul de la ventilation rendue par l'insertion en lot, mode incrémental par date, refus d'une configuration incomplète, arrêt sur circuit-breaker.
"""

from __future__ import annotations

import argparse
import logging
from unittest.mock import MagicMock

import pytest

from application.pipeline.extract.base import ExtractionConfigError
from application.pipeline.extract.extract_openalex import OpenalexExtractor, extract_year
from application.ports.pipeline.extract._common import BatchInsertCounts
from application.ports.pipeline.extract.openalex import OpenalexExtractConfig

_LOGGER = logging.getLogger("test")


def _page(nb_works: int, *, next_cursor: str | None = None, count: int | None = None) -> dict:
    meta: dict = {}
    if count is not None:
        meta["count"] = count
    if next_cursor is not None:
        meta["next_cursor"] = next_cursor
    return {"meta": meta, "results": [{"id": f"W{i}"} for i in range(nb_works)]}


def _adapter(pages: list[dict], comptes: list[BatchInsertCounts] | None = None) -> MagicMock:
    a = MagicMock()
    a.fetch_page.side_effect = pages
    a.insert_batch.side_effect = comptes or [
        BatchInsertCounts(new=len(p["results"]), updated=0, unchanged=0) for p in pages
    ]
    return a


def test_pagination_jusqu_a_l_epuisement_du_curseur():
    adapter = _adapter([_page(2, next_cursor="c2", count=3), _page(1)])
    assert extract_year(adapter, MagicMock(), ["I1"], _LOGGER, year=2024) == (3, 0, 0)


def test_ventilation_cumulee_sur_les_pages():
    pages = [_page(1, next_cursor="c2", count=2), _page(1)]
    comptes = [
        BatchInsertCounts(new=1, updated=0, unchanged=0),
        BatchInsertCounts(new=0, updated=1, unchanged=3),
    ]
    adapter = _adapter(pages, comptes)
    assert extract_year(adapter, MagicMock(), ["I1"], _LOGGER) == (1, 1, 3)
    assert adapter.insert_batch.call_count == 2


def test_page_sans_resultat_interrompt():
    adapter = _adapter([_page(0, next_cursor="c2", count=10)])
    assert extract_year(adapter, MagicMock(), ["I1"], _LOGGER) == (0, 0, 0)
    assert adapter.insert_batch.call_count == 0


def test_dry_run_s_arrete_apres_le_decompte():
    adapter = _adapter([_page(3, next_cursor="c2", count=3)])
    assert extract_year(adapter, MagicMock(), ["I1"], _LOGGER, dry_run=True) == (0, 0, 0)
    assert adapter.fetch_page.call_count == 1


def _config(**surcharges) -> OpenalexExtractConfig:
    valeurs: dict = {
        "base_url": "https://example/",
        "institution_ids": ["I1"],
        "credentials_missing": None,
    }
    valeurs.update(surcharges)
    return OpenalexExtractConfig(**valeurs)


def _extracteur(adapter: MagicMock, config: OpenalexExtractConfig, annees: list[int]):
    adapter.load_config.return_value = config
    adapter.get_years.return_value = annees
    return OpenalexExtractor(MagicMock(), _LOGGER, adapter)


def _args(**surcharges) -> argparse.Namespace:
    valeurs: dict = {"dry_run": False, "year": None, "start_year": None, "since": None}
    valeurs.update(surcharges)
    return argparse.Namespace(**valeurs)


def test_run_parcourt_les_annees_de_la_configuration():
    adapter = _adapter([_page(1, count=1), _page(1, count=1)])
    metrics = _extracteur(adapter, _config(), [2023, 2024]).run(_args())
    assert metrics.new == 2


def test_run_avec_une_annee_demandee_ignore_la_configuration():
    adapter = _adapter([_page(1, count=1)])
    _extracteur(adapter, _config(), [2020, 2021]).run(_args(year=2024))
    assert adapter.fetch_page.call_args.kwargs["year"] == 2024


def test_run_incremental_fait_une_seule_passe_sur_la_date():
    """Avec `--since`, l'extraction porte sur les documents modifiés depuis cette date, sans parcours par année."""
    adapter = _adapter([_page(1, count=1)])
    _extracteur(adapter, _config(), [2020, 2021, 2022]).run(_args(since="2026-01-01"))
    assert adapter.fetch_page.call_count == 1
    assert adapter.fetch_page.call_args.kwargs["since"] == "2026-01-01"


def test_run_sans_institution_refuse():
    with pytest.raises(ExtractionConfigError, match="aucun institution_id"):
        _extracteur(_adapter([]), _config(institution_ids=[]), [2024]).run(_args())


def test_run_sans_identifiants_de_connexion_refuse():
    with pytest.raises(ExtractionConfigError, match="clé API"):
        _extracteur(_adapter([]), _config(credentials_missing="clé API OpenAlex absente"), []).run(
            _args()
        )


def test_run_s_arrete_quand_la_source_est_a_bout():
    adapter = _adapter([])
    breaker = MagicMock()
    breaker.tripped = True
    metrics = _extracteur(adapter, _config(), [2023, 2024]).run(_args(), breaker=breaker)
    assert metrics.total == 0
    assert adapter.fetch_page.call_count == 0
