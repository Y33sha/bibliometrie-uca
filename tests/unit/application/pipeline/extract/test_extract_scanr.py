"""Tests unitaires de l'orchestrateur d'extraction ScanR.

Pas de réseau ni de base : un faux `ScanrExtractAdapter` sert des pages scriptées, et la connexion est un mock dont seul `commit` est appelé. Ce qui est éprouvé ici est le pilotage — pagination `search_after` jusqu'à la page vide, comptage du routage rendu par l'upsert, refus d'une configuration incomplète, arrêt sur circuit-breaker.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from application.pipeline.extract.base import ExtractionConfigError
from application.pipeline.extract.extract_scanr import ScanrExtractor, extract_year
from application.ports.pipeline.extract._common import UpsertOutcome
from application.ports.pipeline.extract.scanr import ScanrExtractConfig
from pipeline.progression import Progression
from tests.helpers.extractors import arguments_du_run, extracteur

_LOGGER = logging.getLogger("test")


def _avancement() -> Progression:
    return Progression(None, "ScanR", None)


def _hit(identifiant: str, route: UpsertOutcome = UpsertOutcome.NEW) -> dict:
    """Document Elasticsearch minimal : la source, et la clé de tri qui sert de curseur."""
    return {"_source": {"id": identifiant, "_route": route}, "sort": [identifiant]}


def _page(hits: list[dict]) -> dict:
    return {"hits": {"hits": hits}}


def _adapter(pages: list[dict]) -> MagicMock:
    a = MagicMock()
    a.build_query.return_value = {"q": "…"}
    a.count.return_value = sum(len(p["hits"]["hits"]) for p in pages)
    a.extract_id.side_effect = lambda doc: doc.get("id", "")
    a.upsert_doc.side_effect = lambda conn, doc: doc["_route"]
    a.fetch_page.side_effect = pages
    return a


def _extraire(adapter: MagicMock) -> tuple[int, int, int, int]:
    return extract_year(adapter, MagicMock(), 2024, ["S1"], _LOGGER, _avancement())


def test_pagination_jusqu_a_la_page_vide():
    adapter = _adapter([_page([_hit("a"), _hit("b")]), _page([_hit("c")]), _page([])])
    assert _extraire(adapter) == (3, 3, 0, 0)


def test_routage_par_sort_de_l_upsert():
    adapter = _adapter(
        [
            _page(
                [
                    _hit("a", UpsertOutcome.NEW),
                    _hit("b", UpsertOutcome.UPDATED),
                    _hit("c", UpsertOutcome.UNCHANGED),
                ]
            ),
            _page([]),
        ]
    )
    assert _extraire(adapter) == (3, 1, 1, 1)


def test_document_sans_identifiant_ignore():
    adapter = _adapter([_page([_hit(""), _hit("b")]), _page([])])
    assert _extraire(adapter)[:2] == (1, 1)


def test_le_curseur_suit_la_cle_de_tri_du_dernier_document():
    adapter = _adapter([_page([_hit("a"), _hit("b")]), _page([])])
    _extraire(adapter)
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


def test_run_parcourt_les_annees_de_la_configuration():
    adapter = _adapter([_page([_hit("a")]), _page([]), _page([_hit("b")]), _page([])])
    metrics = extracteur(ScanrExtractor, adapter, _config(), [2023, 2024]).run(arguments_du_run())
    assert metrics.new == 2
    assert [appel.args[0] for appel in adapter.count.call_args_list] == [2023, 2024]


def test_run_avec_une_annee_demandee_ignore_la_configuration():
    adapter = _adapter([_page([_hit("a")]), _page([])])
    metrics = extracteur(ScanrExtractor, adapter, _config(), [2020, 2021, 2022]).run(
        arguments_du_run(year=2024)
    )
    assert metrics.total == 1
    assert adapter.build_query.call_args_list[0].args[0] == 2024


def test_run_sans_affiliation_refuse():
    adapter = _adapter([])
    with pytest.raises(ExtractionConfigError, match="aucun affiliation_id"):
        extracteur(ScanrExtractor, adapter, _config(affiliation_ids=[]), [2024]).run(
            arguments_du_run()
        )


def test_run_sans_identifiants_de_connexion_refuse():
    adapter = _adapter([])
    with pytest.raises(ExtractionConfigError, match="mot de passe"):
        extracteur(
            ScanrExtractor,
            adapter,
            _config(credentials_missing="mot de passe ScanR absent"),
            [2024],
        ).run(arguments_du_run())


def test_run_s_arrete_quand_la_source_est_a_bout():
    adapter = _adapter([])
    breaker = MagicMock()
    breaker.tripped = True
    metrics = extracteur(ScanrExtractor, adapter, _config(), [2023, 2024]).run(
        arguments_du_run(), breaker=breaker
    )
    assert metrics.total == 0
    assert adapter.fetch_page.call_count == 0
