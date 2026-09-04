"""Tests unitaires de l'orchestrateur d'extraction Web of Science.

Pas de réseau ni de base : un faux `WosExtractAdapter` sert des pages scriptées, et la connexion est un mock dont seul `commit` est appelé. Les pauses sont interceptées, la fixture `_sans_pause` remplaçant `time.sleep`.

Ce qui est éprouvé ici est le pilotage — pagination sur `firstRecord`, abandon après trois pages vides consécutives, plafond de l'API, isolement de l'échec d'une année, refus d'une configuration incomplète, arrêt sur circuit-breaker.
"""

from __future__ import annotations

import argparse
import logging
from unittest.mock import MagicMock

import pytest

from application.pipeline.extract import extract_wos
from application.pipeline.extract.base import ExtractionConfigError
from application.pipeline.extract.extract_wos import WosExtractor, extract_year
from application.ports.pipeline.extract._common import BatchInsertCounts
from application.ports.pipeline.extract.wos import WosExtractConfig

_LOGGER = logging.getLogger("test")


@pytest.fixture(autouse=True)
def _sans_pause(monkeypatch):
    """Les pauses de ménagement de l'API ne ralentissent pas la suite."""
    monkeypatch.setattr(extract_wos.time, "sleep", lambda _: None)


def _adapter(pages: list[list[dict]], *, total: int, comptes=None) -> MagicMock:
    """Faux adapter servant `pages` successivement, chaque page étant une liste de records."""
    a = MagicMock()
    a.build_query.return_value = "TS=(…)"
    a.get_records_found.return_value = total
    a.check_quota.return_value = "1000"
    a.fetch_page.side_effect = [{"page": i} for i in range(len(pages) + 1)]
    a.get_records.side_effect = pages
    # Une page vide ne déclenche pas d'insertion : les comptes ne portent que sur les autres.
    a.insert_batch.side_effect = comptes or [
        BatchInsertCounts(new=len(p), updated=0, unchanged=0) for p in pages if p
    ]
    return a


def _records(n: int) -> list[dict]:
    return [{"UID": f"WOS:{i}"} for i in range(n)]


def test_pagination_sur_le_premier_record():
    adapter = _adapter([_records(2), _records(1)], total=3)
    assert extract_year(adapter, MagicMock(), 2024, ["UCA"], _LOGGER) == (3, 0, 0)
    # Deuxième page demandée à partir du record 3.
    assert adapter.fetch_page.call_args_list[1].args[1] == 3


def test_ventilation_cumulee_sur_les_pages():
    comptes = [
        BatchInsertCounts(new=1, updated=0, unchanged=0),
        BatchInsertCounts(new=0, updated=2, unchanged=1),
    ]
    adapter = _adapter([_records(1), _records(1)], total=2, comptes=comptes)
    assert extract_year(adapter, MagicMock(), 2024, ["UCA"], _LOGGER) == (1, 2, 1)


def test_requete_impossible():
    adapter = _adapter([], total=0)
    adapter.fetch_page.side_effect = [None]
    assert extract_year(adapter, MagicMock(), 2024, ["UCA"], _LOGGER) == (0, 0, 0)


def test_aucun_record_trouve():
    adapter = _adapter([], total=0)
    assert extract_year(adapter, MagicMock(), 2024, ["UCA"], _LOGGER) == (0, 0, 0)
    assert adapter.insert_batch.call_count == 0


def test_dry_run_s_arrete_apres_le_decompte():
    adapter = _adapter([_records(5)], total=5)
    assert extract_year(adapter, MagicMock(), 2024, ["UCA"], _LOGGER, dry_run=True) == (0, 0, 0)
    assert adapter.insert_batch.call_count == 0


def test_trois_pages_vides_consecutives_arretent_l_annee():
    adapter = _adapter([[], [], []], total=10)
    adapter.fetch_page.side_effect = [{"page": i} for i in range(6)]
    assert extract_year(adapter, MagicMock(), 2024, ["UCA"], _LOGGER) == (0, 0, 0)


def test_une_page_vide_isolee_est_retentee():
    adapter = _adapter([[], _records(2)], total=2)
    adapter.fetch_page.side_effect = [{"page": i} for i in range(4)]
    assert extract_year(adapter, MagicMock(), 2024, ["UCA"], _LOGGER) == (2, 0, 0)


def test_plafond_de_l_api_interrompt():
    """L'API refuse un `firstRecord` au-delà de cent mille : la boucle s'arrête là."""
    adapter = _adapter([_records(1)], total=200_000)
    adapter.get_records.side_effect = [[{"UID": f"WOS:{i}"} for i in range(100_001)]]
    adapter.insert_batch.side_effect = [BatchInsertCounts(new=100_001, updated=0, unchanged=0)]
    new, _, _ = extract_year(adapter, MagicMock(), 2024, ["UCA"], _LOGGER)
    assert new == 100_001
    assert adapter.fetch_page.call_count == 1


def _config(**surcharges) -> WosExtractConfig:
    valeurs: dict = {
        "base_url": "https://example/",
        "affiliations": ["UCA"],
        "credentials_missing": None,
    }
    valeurs.update(surcharges)
    return WosExtractConfig(**valeurs)


def _extracteur(adapter: MagicMock, config: WosExtractConfig, annees: list[int]):
    adapter.load_config.return_value = config
    adapter.get_years.return_value = annees
    return WosExtractor(MagicMock(), _LOGGER, adapter)


def _args(**surcharges) -> argparse.Namespace:
    valeurs: dict = {"dry_run": False, "year": None, "start_year": None}
    valeurs.update(surcharges)
    return argparse.Namespace(**valeurs)


def test_run_parcourt_les_annees_de_la_configuration():
    adapter = _adapter([_records(1), _records(1)], total=1)
    adapter.fetch_page.side_effect = [{"page": i} for i in range(4)]
    metrics = _extracteur(adapter, _config(), [2023, 2024]).run(_args())
    assert metrics.new == 2


def test_run_isole_l_echec_d_une_annee():
    """Une année qui lève laisse la suivante s'exécuter."""
    adapter = _adapter([_records(1)], total=1)
    adapter.fetch_page.side_effect = [RuntimeError("API en panne"), {"page": 0}, {"page": 1}]
    metrics = _extracteur(adapter, _config(), [2023, 2024]).run(_args())
    assert metrics.new == 1


def test_run_survit_a_un_quota_illisible():
    adapter = _adapter([], total=0)
    adapter.check_quota.side_effect = RuntimeError("service indisponible")
    metrics = _extracteur(adapter, _config(), [2024]).run(_args())
    assert metrics.total == 0


def test_run_sans_affiliation_refuse():
    with pytest.raises(ExtractionConfigError, match="aucune affiliation"):
        _extracteur(_adapter([], total=0), _config(affiliations=[]), [2024]).run(_args())


def test_run_sans_cle_api_refuse():
    with pytest.raises(ExtractionConfigError, match="clé API"):
        _extracteur(
            _adapter([], total=0), _config(credentials_missing="clé API WoS absente"), []
        ).run(_args())


def test_run_s_arrete_quand_la_source_est_a_bout():
    adapter = _adapter([], total=0)
    breaker = MagicMock()
    breaker.tripped = True
    metrics = _extracteur(adapter, _config(), [2023, 2024]).run(_args(), breaker=breaker)
    assert metrics.total == 0
    assert adapter.fetch_page.call_count == 0
