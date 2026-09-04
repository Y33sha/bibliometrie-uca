"""Tests unitaires de l'orchestrateur d'extraction ScanR.

Pas de réseau ni de base : un faux `ScanrExtractAdapter` sert des pages scriptées, et la connexion est un mock dont seul `commit` est appelé. Ce qui est éprouvé ici est le pilotage — pagination `search_after` jusqu'à la page vide, comptage du routage rendu par l'upsert, refus d'une configuration incomplète, arrêt sur circuit-breaker.
"""

from __future__ import annotations

import argparse
import logging
from unittest.mock import MagicMock

import pytest

from application.pipeline.extract.base import ExtractionConfigError
from application.pipeline.extract.extract_scanr import ScanrExtractor, extract_year
from application.ports.pipeline.extract._common import UpsertOutcome
from application.ports.pipeline.extract.scanr import ScanrExtractConfig

_LOGGER = logging.getLogger("test")


def _hit(identifiant: str, route: UpsertOutcome = UpsertOutcome.NEW) -> dict:
    """Document Elasticsearch minimal : la source, et la clé de tri qui sert de curseur."""
    return {"_source": {"id": identifiant, "_route": route}, "sort": [identifiant]}


def _page(hits: list[dict], total: int | None = None) -> dict:
    corps: dict = {"hits": {"hits": hits}}
    if total is not None:
        corps["hits"]["total"] = {"value": total}
    return corps


def _adapter(pages: list[dict]) -> MagicMock:
    a = MagicMock()
    a.build_query.return_value = {"q": "…"}
    a.extract_id.side_effect = lambda doc: doc.get("id", "")
    a.upsert_doc.side_effect = lambda conn, doc: doc["_route"]
    a.fetch_page.side_effect = pages
    return a


def test_pagination_jusqu_a_la_page_vide():
    adapter = _adapter([_page([_hit("a"), _hit("b")], total=3), _page([_hit("c")]), _page([])])
    assert extract_year(adapter, MagicMock(), 2024, ["S1"], _LOGGER) == (3, 3, 0, 0)


def test_routage_par_sort_de_l_upsert():
    adapter = _adapter(
        [
            _page(
                [
                    _hit("a", UpsertOutcome.NEW),
                    _hit("b", UpsertOutcome.UPDATED),
                    _hit("c", UpsertOutcome.UNCHANGED),
                ],
                total=3,
            ),
            _page([]),
        ]
    )
    assert extract_year(adapter, MagicMock(), 2024, ["S1"], _LOGGER) == (3, 1, 1, 1)


def test_document_sans_identifiant_ignore():
    adapter = _adapter([_page([_hit(""), _hit("b")], total=2), _page([])])
    assert extract_year(adapter, MagicMock(), 2024, ["S1"], _LOGGER)[1] == 1


def test_dry_run_s_arrete_apres_le_decompte():
    adapter = _adapter([_page([_hit("a")], total=7)])
    assert extract_year(adapter, MagicMock(), 2024, ["S1"], _LOGGER, dry_run=True) == (7, 0, 0, 0)
    assert adapter.fetch_page.call_count == 1


def test_le_curseur_suit_la_cle_de_tri_du_dernier_document():
    adapter = _adapter([_page([_hit("a"), _hit("b")], total=2), _page([])])
    extract_year(adapter, MagicMock(), 2024, ["S1"], _LOGGER)
    # Premier appel sans curseur, second reprenant la clé de tri du dernier document servi.
    assert adapter.build_query.call_args_list[0].args[2] is None
    assert adapter.build_query.call_args_list[1].args[2] == ["b"]


def _config(**surcharges) -> ScanrExtractConfig:
    valeurs: dict = {
        "base_url": "https://example/",
        "affiliation_ids": ["S1"],
        "credentials_missing": None,
    }
    valeurs.update(surcharges)
    return ScanrExtractConfig(**valeurs)


def _extracteur(adapter: MagicMock, config: ScanrExtractConfig, annees: list[int]):
    adapter.load_config.return_value = config
    adapter.get_years.return_value = annees
    return ScanrExtractor(MagicMock(), _LOGGER, adapter)


def _args(**surcharges) -> argparse.Namespace:
    valeurs: dict = {"dry_run": False, "year": None, "start_year": None}
    valeurs.update(surcharges)
    return argparse.Namespace(**valeurs)


def test_run_parcourt_les_annees_de_la_configuration():
    adapter = _adapter(
        [_page([_hit("a")], total=1), _page([]), _page([_hit("b")], total=1), _page([])]
    )
    metrics = _extracteur(adapter, _config(), [2023, 2024]).run(_args())
    assert metrics.new == 2


def test_run_avec_une_annee_demandee_ignore_la_configuration():
    adapter = _adapter([_page([_hit("a")], total=1), _page([])])
    metrics = _extracteur(adapter, _config(), [2020, 2021, 2022]).run(_args(year=2024))
    assert metrics.total == 1
    assert adapter.build_query.call_args_list[0].args[0] == 2024


def test_run_sans_affiliation_refuse():
    adapter = _adapter([])
    with pytest.raises(ExtractionConfigError, match="aucun affiliation_id"):
        _extracteur(adapter, _config(affiliation_ids=[]), [2024]).run(_args())


def test_run_sans_identifiants_de_connexion_refuse():
    adapter = _adapter([])
    with pytest.raises(ExtractionConfigError, match="mot de passe"):
        _extracteur(adapter, _config(credentials_missing="mot de passe ScanR absent"), [2024]).run(
            _args()
        )


def test_run_s_arrete_quand_la_source_est_a_bout():
    adapter = _adapter([])
    breaker = MagicMock()
    breaker.tripped = True
    metrics = _extracteur(adapter, _config(), [2023, 2024]).run(_args(), breaker=breaker)
    assert metrics.total == 0
    assert adapter.fetch_page.call_count == 0
