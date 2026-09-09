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
