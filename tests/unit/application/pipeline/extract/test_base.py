"""Tests unitaires de `application.pipeline.extract.base.SourceExtractor`.

Couvre le cycle `run` (load_config → setup_logging → extract_all → log_summary) et la default impl de `log_summary`.

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
        super().__init__(conn, logger)
        self._config = config or {"affiliations": ["UCA"]}
        self._metrics = metrics or PhaseMetrics(new=42)
        self.load_config_calls = 0
        self.extract_all_calls: list[dict[str, Any]] = []
        self.setup_logging_calls = 0
        self.log_summary_calls: list[PhaseMetrics] = []

    def load_config(self, conn):  # type: ignore[no-untyped-def]
        self.load_config_calls += 1
        return self._config

    def extract_all(self, args, config):  # type: ignore[no-untyped-def]
        self.extract_all_calls.append({"args": args, "config": config})
        return self._metrics

    def setup_logging(self, args, config):  # type: ignore[no-untyped-def]
        self.setup_logging_calls += 1

    def log_summary(self, metrics, args):  # type: ignore[no-untyped-def]
        # Override pour capturer (sinon la default impl loggue juste un message).
        self.log_summary_calls.append(metrics)


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test_extract_base")


@pytest.fixture
def conn():
    return MagicMock()


class TestRun:
    def test_happy_path_calls_pipeline_in_order(self, conn, logger):
        ext = _FakeExtractor(conn, logger)
        args = argparse.Namespace(dry_run=False)

        metrics = ext.run(args)

        assert ext.load_config_calls == 1
        assert ext.setup_logging_calls == 1
        # extract_all reçoit args, config.
        assert len(ext.extract_all_calls) == 1
        call = ext.extract_all_calls[0]
        assert call["args"] is args
        assert call["config"] == {"affiliations": ["UCA"]}
        # log_summary reçoit les metrics retournés.
        assert ext.log_summary_calls == [metrics]
        assert metrics.new == 42

    def test_no_args_defaults_to_non_dry_run(self, conn, logger):
        """`run()` sans argument fabrique un Namespace(dry_run=False)."""
        ext = _FakeExtractor(conn, logger)

        ext.run()

        assert ext.extract_all_calls[0]["args"].dry_run is False


class _MinimalExtractor(SourceExtractor):
    """Extracteur qui n'override pas `log_summary` (pour tester la default impl)."""

    SOURCE = "minimal"

    def load_config(self, conn):  # type: ignore[no-untyped-def]
        return {}

    def extract_all(self, args, config):  # type: ignore[no-untyped-def]
        return PhaseMetrics(new=3)


class TestLogSummaryDefault:
    def test_default_logs_terminé_message(self, conn, caplog):
        logger = logging.getLogger("test_log_summary_default")
        ext = _MinimalExtractor(conn, logger)
        metrics = PhaseMetrics(new=3)

        with caplog.at_level(logging.INFO, logger=logger.name):
            ext.log_summary(metrics, argparse.Namespace(dry_run=False))

        assert any("Terminé" in r.getMessage() for r in caplog.records)
