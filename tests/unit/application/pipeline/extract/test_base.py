"""Tests unitaires de `application.pipeline.extract.base.SourceExtractor`.

Couvre le cycle `run` (load_config → setup_logging → extract_all) et le log de résumé.

Pas de DB ni de réseau : fake extractor avec `load_config`/`extract_all` déterministes et `Connection` mockée.
"""

from __future__ import annotations

import argparse
import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from application.pipeline.extract.base import SourceExtractor
from application.pipeline.metrics import PhaseMetrics


class _FakeExtractor(SourceExtractor):
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

    def extract_all(self, args, config):  # type: ignore[no-untyped-def]
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


class _ParAnnee(SourceExtractor):
    """Extracteur dont chaque année rapporte un nouveau document et des inchangés, selon `volumes`."""

    SOURCE = "hal"

    def __init__(self, logger, volumes: dict[int, int]) -> None:
        super().__init__(MagicMock(), logger, MagicMock())
        self.volumes = volumes
        self.libelles: list[str] = []
        self.totaux: list[int | None] = []
        self.avancement = None

    def load_config(self, conn):  # type: ignore[no-untyped-def]
        return None

    def extract_all(self, args, config):  # type: ignore[no-untyped-def]
        def extrait(annee, avancement):
            self.avancement = avancement
            self.libelles.append(avancement._libelle)
            self.totaux.append(avancement._total)
            return PhaseMetrics(new=1, unchanged=self.volumes[annee] - 1)

        return self._extrait_par_annee(list(self.volumes), self.volumes.__getitem__, extrait)


def _args() -> argparse.Namespace:
    return argparse.Namespace(year=None, start_year=None)


class TestExtractionParAnnee:
    """Une barre par source, dont le libellé suit l'année en cours, puis un bilan."""

    def test_le_libelle_suit_l_annee_en_cours(self, logger):
        ext = _ParAnnee(logger, {2023: 2, 2024: 3})
        ext.run(_args())
        assert "2023" in ext.libelles[0]
        assert "2024" in ext.libelles[1]

    def test_une_extraction_complete_affiche_la_plage_d_annees(self, logger):
        ext = _ParAnnee(logger, {2023: 2, 2024: 3})
        ext.run(_args())
        assert ext.avancement._libelle.rstrip().endswith("2023-2024")

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

    def test_une_source_a_bout_nomme_les_annees_sautees(self, logger, caplog):
        breaker = MagicMock()
        breaker.tripped = True
        with caplog.at_level(logging.WARNING, logger=logger.name):
            _ParAnnee(logger, {2023: 2, 2024: 3}).run(_args(), breaker=breaker)
        assert "années 2023, 2024 sautées" in caplog.text


class TestRun:
    def test_happy_path_calls_pipeline_in_order(self, conn, logger):
        ext = _FakeExtractor(conn, logger)
        args = argparse.Namespace(year=None, start_year=None)

        metrics = ext.run(args)

        assert ext.load_config_calls == 1
        assert ext.setup_logging_calls == 1
        # extract_all reçoit args, config.
        assert len(ext.extract_all_calls) == 1
        call = ext.extract_all_calls[0]
        assert call["args"] is args
        assert call["config"] == {"affiliations": ["UCA"]}
        assert metrics.new == 42
