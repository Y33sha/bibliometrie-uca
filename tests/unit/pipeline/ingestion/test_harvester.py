"""Tests unitaires de `pipeline.ingestion.common.harvester.SourceHarvester`.

Couvre le moissonnage par année, le bilan et la source sans configuration.

Sans base ni réseau : un faux moissonneur déterministe et une connexion simulée.
"""

from __future__ import annotations

import argparse
import logging
from unittest.mock import MagicMock

import pytest

from pipeline.http.circuit_breaker import SourceUnavailableError, source_circuit_breaker
from pipeline.ingestion.common import harvester
from pipeline.ingestion.common.harvester import (
    HarvestConfigError,
    HarvestWindow,
    SourceHarvester,
    run_harvest,
)


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test_extract_base")


@pytest.fixture
def conn():
    return MagicMock()


class _ParAnnee(SourceHarvester):
    """Moissonneur rapportant, pour chaque année, un document inséré et des documents inchangés selon `volumes`. La source est indisponible à partir de l'année `unavailable_from`. L'année `failing` échoue après avoir écrit son document inséré."""

    SOURCE = "hal"

    def __init__(
        self,
        logger,
        volumes: dict[int, int],
        *,
        unavailable_from: int | None = None,
        failing: int | None = None,
    ) -> None:
        super().__init__(MagicMock(), logger, MagicMock())
        self.volumes = volumes
        self.unavailable_from = unavailable_from
        self.failing = failing
        self.log_format: list[str] = []
        self.totaux: list[int | None] = []
        self.progress = None

    def run(self, window):  # type: ignore[no-untyped-def]
        def harvest_step(year, progress, metrics):
            self.progress = progress
            self.log_format.append(progress._label)
            self.totaux.append(progress._total)
            if self.unavailable_from is not None and year >= self.unavailable_from:
                raise SourceUnavailableError(self.SOURCE)
            metrics.add(new=1)
            if year == self.failing:
                raise ValueError("réponse illisible")
            metrics.add(unchanged=self.volumes[year] - 1)

        return self._harvest_by_year(list(self.volumes), self.volumes.__getitem__, harvest_step)


def _args() -> argparse.Namespace:
    return HarvestWindow()


class TestExtractionParAnnee:
    """Une barre par source, libellée par l'année en cours, puis un bilan."""

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

    def test_le_bilan_somme_les_annees(self, logger):
        metrics = _ParAnnee(logger, {2023: 2, 2024: 3}).run(_args())
        assert (metrics.new, metrics.unchanged) == (2, 3)

    def test_une_source_indisponible_coupe_la_source_et_garde_les_annees_extraites(self, logger):
        with source_circuit_breaker("hal") as breaker:
            metrics = _ParAnnee(logger, {2023: 2, 2024: 3, 2025: 1}, unavailable_from=2024).run(
                _args()
            )
        assert metrics.total == 2
        assert breaker.tripped

    def test_une_erreur_sur_une_annee_passe_a_la_suivante(self, logger, caplog):
        """L'erreur est journalisée, la page en cours annulée, et les écritures déjà comptées restent dans le bilan."""
        ext = _ParAnnee(logger, {2023: 2, 2024: 3, 2025: 1}, failing=2024)
        with caplog.at_level(logging.ERROR):
            metrics = ext.run(_args())
        assert (metrics.new, metrics.unchanged) == (3, 1)
        ext.conn.rollback.assert_called_once()
        assert "réponse illisible" in caplog.text

    def test_une_erreur_de_decompte_compte_l_annee_pour_zero(self, logger):
        ext = _ParAnnee(logger, {2023: 2, 2024: 3})

        def count_year(year: int) -> int:
            if year == 2024:
                raise ValueError("réponse illisible")
            return ext.volumes[year]

        assert sum(ext._count(count_year, year) for year in ext.volumes) == 2


def test_une_source_non_configuree_est_sautee_avec_un_signal(contexte):
    class _SansConfiguration:
        def run(self, window):
            raise HarvestConfigError("aucun PPN")

    metrics = run_harvest(
        contexte(), "theses", lambda conn, log: _SansConfiguration(), HarvestWindow()
    )

    assert [s["code"] for s in metrics.signals] == ["source_unconfigured"]


def test_une_source_sans_identifiant_dans_le_perimetre_leve_une_erreur_de_configuration(
    monkeypatch, logger
):
    monkeypatch.setattr(harvester, "get_extraction_api_ids", lambda conn, source: [])
    ext = _ParAnnee(logger, {})
    ext.MISSING_API_IDS = "aucune affiliation"

    with pytest.raises(HarvestConfigError, match="aucune affiliation"):
        ext._api_ids()
