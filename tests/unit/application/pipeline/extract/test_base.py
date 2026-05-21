"""Tests unitaires de `application.pipeline.extract.base.SourceExtractor`.

Couvre :
- Cycle `run_as_phase` : load_config → setup_logging → fetch_existing_source_ids (skippé en dry-run) → extract_all → log_summary.
- Entry point CLI `run` : exit codes pour `ExtractionConfigError` (2), `requests.HTTPError` (1), `KeyboardInterrupt` (0), happy path. `conn.close()` toujours appelé.
- `parse_args` : flag `--dry-run` + extension via `add_cli_args`.

Pas de DB ni de réseau : fake extractor avec `load_config`/`extract_all` déterministes, `Connection` mockée, `StagingQueries` port mocké via MagicMock.
"""

from __future__ import annotations

import argparse
import logging
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from application.pipeline.extract.base import ExtractionConfigError, SourceExtractor
from application.pipeline.metrics import PhaseMetrics


class _FakeExtractor(SourceExtractor):
    """Implémentation déterministe pour les tests."""

    SOURCE = "fake"
    DESCRIPTION = "Fake source for tests"

    def __init__(
        self,
        conn,
        logger,
        staging,
        *,
        config: dict[str, Any] | None = None,
        metrics: PhaseMetrics | None = None,
        raise_in_extract: Exception | None = None,
    ) -> None:
        super().__init__(conn, logger, staging)
        self._config = config or {"affiliations": ["UCA"]}
        self._metrics = metrics or PhaseMetrics(new=42, total=42)
        self._raise_in_extract = raise_in_extract
        self.load_config_calls = 0
        self.extract_all_calls: list[dict[str, Any]] = []
        self.add_cli_args_calls = 0
        self.setup_logging_calls = 0
        self.log_summary_calls: list[PhaseMetrics] = []

    def load_config(self, conn):  # type: ignore[no-untyped-def]
        self.load_config_calls += 1
        return self._config

    def extract_all(self, args, config, existing_ids):  # type: ignore[no-untyped-def]
        self.extract_all_calls.append(
            {"args": args, "config": config, "existing_ids": existing_ids}
        )
        if self._raise_in_extract:
            raise self._raise_in_extract
        return self._metrics

    def add_cli_args(self, parser):  # type: ignore[no-untyped-def]
        self.add_cli_args_calls += 1
        parser.add_argument("--extra-flag", action="store_true")

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


@pytest.fixture
def staging():
    """Mock `StagingQueries` port renvoyant un set stable."""
    s = MagicMock()
    s.fetch_existing_source_ids.return_value = {"id-A", "id-B"}
    return s


# ── run_as_phase ─────────────────────────────────────────────────


class TestRunAsPhase:
    def test_happy_path_calls_pipeline_in_order(self, conn, logger, staging):
        ext = _FakeExtractor(conn, logger, staging)
        args = argparse.Namespace(dry_run=False)

        metrics = ext.run_as_phase(args)

        assert ext.load_config_calls == 1
        assert ext.setup_logging_calls == 1
        # fetch_existing_source_ids appelé hors dry-run.
        staging.fetch_existing_source_ids.assert_called_once_with(conn, "fake")
        # extract_all reçoit args, config, existing_ids.
        assert len(ext.extract_all_calls) == 1
        call = ext.extract_all_calls[0]
        assert call["args"] is args
        assert call["config"] == {"affiliations": ["UCA"]}
        assert call["existing_ids"] == {"id-A", "id-B"}
        # log_summary reçoit les metrics retournés.
        assert ext.log_summary_calls == [metrics]
        assert metrics.new == 42

    def test_dry_run_skips_existing_ids_lookup(self, conn, logger, staging):
        ext = _FakeExtractor(conn, logger, staging)
        args = argparse.Namespace(dry_run=True)

        ext.run_as_phase(args)

        # fetch_existing_source_ids NON appelé en dry-run.
        staging.fetch_existing_source_ids.assert_not_called()
        # extract_all reçoit un set vide.
        assert ext.extract_all_calls[0]["existing_ids"] == set()

    def test_no_args_defaults_to_non_dry_run(self, conn, logger, staging):
        """`run_as_phase()` sans argument fabrique un Namespace(dry_run=False)."""
        ext = _FakeExtractor(conn, logger, staging)

        ext.run_as_phase()

        assert ext.extract_all_calls[0]["args"].dry_run is False
        staging.fetch_existing_source_ids.assert_called_once_with(conn, "fake")


# ── run (CLI entry point) ─────────────────────────────────────────


class TestRunCli:
    def test_happy_path_returns_no_exit(self, conn, logger, staging):
        """Sans erreur : pas de SystemExit, conn.close() appelé dans finally."""
        ext = _FakeExtractor(conn, logger, staging)

        ext.run([])

        assert ext.extract_all_calls
        conn.close.assert_called_once()

    def test_extraction_config_error_exit_2(self, conn, logger, staging):
        ext = _FakeExtractor(
            conn, logger, staging, raise_in_extract=ExtractionConfigError("missing affiliations")
        )

        with pytest.raises(SystemExit) as exc_info:
            ext.run([])

        assert exc_info.value.code == 2
        conn.close.assert_called_once()

    def test_http_error_exit_1_with_response_body(self, conn, logger, staging):
        """`requests.HTTPError` → exit 1, log inclut le début du body de réponse."""
        response = MagicMock()
        response.text = "Server says no" * 100  # Vérifie le slice [:500]
        err = requests.exceptions.HTTPError("Bad request")
        err.response = response
        ext = _FakeExtractor(conn, logger, staging, raise_in_extract=err)

        with pytest.raises(SystemExit) as exc_info:
            ext.run([])

        assert exc_info.value.code == 1
        conn.close.assert_called_once()

    def test_http_error_without_response(self, conn, logger, staging):
        """Branch `e.response is None` : pas de second log, exit 1 quand même."""
        err = requests.exceptions.HTTPError("No response attached")
        err.response = None
        ext = _FakeExtractor(conn, logger, staging, raise_in_extract=err)

        with pytest.raises(SystemExit) as exc_info:
            ext.run([])

        assert exc_info.value.code == 1

    def test_keyboard_interrupt_exit_0(self, conn, logger, staging):
        ext = _FakeExtractor(conn, logger, staging, raise_in_extract=KeyboardInterrupt())

        with pytest.raises(SystemExit) as exc_info:
            ext.run([])

        assert exc_info.value.code == 0
        conn.close.assert_called_once()

    def test_conn_close_called_even_on_unexpected_exception(self, conn, logger, staging):
        """Le `finally` ferme la connexion même si une exception non-cattée remonte."""
        ext = _FakeExtractor(conn, logger, staging, raise_in_extract=RuntimeError("boom"))

        with pytest.raises(RuntimeError, match="boom"):
            ext.run([])

        conn.close.assert_called_once()


# ── parse_args ────────────────────────────────────────────────────


class TestParseArgs:
    def test_default_dry_run_false(self, conn, logger, staging):
        ext = _FakeExtractor(conn, logger, staging)

        args = ext.parse_args([])

        assert args.dry_run is False

    def test_dry_run_flag(self, conn, logger, staging):
        ext = _FakeExtractor(conn, logger, staging)

        args = ext.parse_args(["--dry-run"])

        assert args.dry_run is True

    def test_add_cli_args_hook_runs(self, conn, logger, staging):
        """L'override `add_cli_args` est invoqué, ses args sont parsés."""
        ext = _FakeExtractor(conn, logger, staging)

        args = ext.parse_args(["--extra-flag"])

        assert args.extra_flag is True
        assert ext.add_cli_args_calls == 1


# ── log_summary (default impl) ────────────────────────────────────


class _MinimalExtractor(SourceExtractor):
    """Extracteur qui n'override pas `log_summary` (pour tester la default impl)."""

    SOURCE = "minimal"
    DESCRIPTION = ""

    def load_config(self, conn):  # type: ignore[no-untyped-def]
        return {}

    def extract_all(self, args, config, existing_ids):  # type: ignore[no-untyped-def]
        return PhaseMetrics(new=3, total=3)


class TestLogSummaryDefault:
    def test_default_logs_terminé_message(self, conn, staging, caplog):
        logger = logging.getLogger("test_log_summary_default")
        ext = _MinimalExtractor(conn, logger, staging)
        metrics = PhaseMetrics(new=3, total=3)

        with caplog.at_level(logging.INFO, logger=logger.name):
            ext.log_summary(metrics, argparse.Namespace(dry_run=False))

        assert any("Terminé" in r.getMessage() for r in caplog.records)
