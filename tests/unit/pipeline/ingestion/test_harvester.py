"""Tests unitaires de `pipeline.ingestion.common.harvester.SourceHarvester`.

Couvre la séquence de `run` (`load_config`, `setup_logging`, puis `harvest_all`) et le bilan journalisé.

Sans base ni réseau : un faux moissonneur déterministe et une connexion simulée.
"""

from __future__ import annotations

import argparse
import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from pipeline.http.circuit_breaker import SourceUnavailableError, source_circuit_breaker
from pipeline.ingestion.common.harvester import (
    HarvestConfigError,
    HarvestWindow,
    SourceHarvester,
    run_harvest,
)
from pipeline.runtime.observability.metrics import PhaseMetrics


class _FakeHarvester(SourceHarvester):
    """Implémentation déterministe pour les tests."""

    SOURCE = "fake"

    def __init__(
        self,
        conn,
        logger,
        *,
        config: dict[str, Any] | None = None,
        metrics: PhaseMetrics | None = None,
    ) -> None:
        super().__init__(conn, logger, MagicMock())
        self._config = config or {"affiliations": ["UCA"]}
        self._metrics = metrics or PhaseMetrics(new=42)
        self.load_config_calls = 0
        self.extract_all_calls: list[dict[str, Any]] = []
        self.setup_logging_calls = 0

    def load_config(self, conn):  # type: ignore[no-untyped-def]
        self.load_config_calls += 1
        return self._config

    def harvest_all(self, args, config):  # type: ignore[no-untyped-def]
        self.extract_all_calls.append({"args": args, "config": config})
        return self._metrics

    def setup_logging(self, args, config):  # type: ignore[no-untyped-def]
        self.setup_logging_calls += 1


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test_extract_base")


@pytest.fixture
def conn():
    return MagicMock()


class _ParAnnee(SourceHarvester):
    """Moissonneur dont chaque année rapporte un document inséré et des documents inchangés, selon `volumes`. La source est indisponible à partir de l'année `unavailable_from`."""

    SOURCE = "hal"

    def __init__(
        self, logger, volumes: dict[int, int], *, unavailable_from: int | None = None
    ) -> None:
        super().__init__(MagicMock(), logger, MagicMock())
        self.volumes = volumes
        self.unavailable_from = unavailable_from
        self.log_format: list[str] = []
        self.totaux: list[int | None] = []
        self.progress = None

    def load_config(self, conn):  # type: ignore[no-untyped-def]
        return None

    def harvest_all(self, args, config):  # type: ignore[no-untyped-def]
        def harvest_step(year, progress):
            self.progress = progress
            self.log_format.append(progress._label)
            self.totaux.append(progress._total)
            if self.unavailable_from is not None and year >= self.unavailable_from:
                raise SourceUnavailableError(self.SOURCE)
            return PhaseMetrics(new=1, unchanged=self.volumes[year] - 1)

        return self._harvest_by_year(list(self.volumes), self.volumes.__getitem__, harvest_step)


def _args() -> argparse.Namespace:
    return argparse.Namespace(year=None, start_year=None)


class TestExtractionParAnnee:
    """Une barre par source, dont le libellé suit l'année en cours, puis un bilan."""

    def test_le_libelle_suit_l_annee_en_cours(self, logger):
        ext = _ParAnnee(logger, {2023: 2, 2024: 3})
        ext.run(_args())
        assert "2023" in ext.log_format[0]
        assert "2024" in ext.log_format[1]

    def test_une_extraction_complete_affiche_la_plage_d_annees(self, logger):
        ext = _ParAnnee(logger, {2023: 2, 2024: 3})
        ext.run(_args())
        assert ext.progress._label.rstrip().endswith("2023-2024")

    def test_le_total_de_la_barre_somme_les_annees(self, logger):
        ext = _ParAnnee(logger, {2023: 2, 2024: 3})
        ext.run(_args())
        assert ext.totaux == [5, 5]

    def test_le_bilan_ventile_les_documents(self, logger, caplog):
        with caplog.at_level(logging.INFO, logger=logger.name):
            _ParAnnee(logger, {2023: 2, 2024: 3}).run(_args())
        assert "5 documents trouvés : 2 nouveaux, 0 mis à jour, 3 inchangés" in caplog.text

    def test_le_bilan_accorde_au_singulier(self, logger, caplog):
        with caplog.at_level(logging.INFO, logger=logger.name):
            _ParAnnee(logger, {2024: 1}).run(_args())
        assert "1 document trouvé : 1 nouveau, 0 mis à jour, 0 inchangé" in caplog.text

    def test_une_source_indisponible_coupe_la_source_et_garde_les_annees_extraites(self, logger):
        with source_circuit_breaker("hal") as breaker:
            metrics = _ParAnnee(logger, {2023: 2, 2024: 3, 2025: 1}, unavailable_from=2024).run(
                _args()
            )
        assert metrics.total == 2
        assert breaker.tripped


class _DUnTenant(_ParAnnee):
    """Moissonneur d'un seul tenant, dont le bilan nomme le critère de recherche."""

    def harvest_all(self, args, config):  # type: ignore[no-untyped-def]
        return self._harvest_at_once(2, lambda progress: PhaseMetrics(new=2), by="ORCID, IdRef")


def test_le_bilan_nomme_le_critere_de_recherche(logger, caplog):
    with caplog.at_level(logging.INFO, logger=logger.name):
        _DUnTenant(logger, {}).run(_args())
    assert "2 documents trouvés par ORCID, IdRef : 2 nouveaux" in caplog.text


class TestRun:
    def test_happy_path_calls_pipeline_in_order(self, conn, logger):
        ext = _FakeHarvester(conn, logger)
        args = argparse.Namespace(year=None, start_year=None)

        metrics = ext.run(args)

        assert ext.load_config_calls == 1
        assert ext.setup_logging_calls == 1
        # harvest_all reçoit args, config.
        assert len(ext.extract_all_calls) == 1
        call = ext.extract_all_calls[0]
        assert call["args"] is args
        assert call["config"] == {"affiliations": ["UCA"]}
        assert metrics.new == 42


def test_une_source_non_configuree_est_sautee_avec_un_signal(contexte):
    class _SansConfiguration:
        def run(self, window):
            raise HarvestConfigError("aucun PPN")

    metrics = run_harvest(
        contexte(), "harvest", "theses", lambda conn, log: _SansConfiguration(), HarvestWindow()
    )

    assert [s["code"] for s in metrics.signals] == ["source_unconfigured"]
