"""Enrichissement des revues par OpenAlex Sources : écriture du type."""

import contextlib
from unittest.mock import MagicMock

import pytest

from pipeline.http.circuit_breaker import get_current_breaker, source_circuit_breaker
from pipeline.transformation.publishing.serials import (
    enrich_serials_from_openalex as serials_mod,
)


@contextlib.contextmanager
def _bound(repo):
    """Branche les fonctions SQL du module, et son store des revues, sur le faux `repo`."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            serials_mod,
            "find_serials_of_unknown_type",
            lambda conn, *a, **k: repo.find_serials_of_unknown_type(*a, **k),
        )
        mp.setattr(serials_mod, "SerialStore", lambda conn: repo)
        yield


class TestSerialsType:
    def _run(self, answer):
        serial_repo = MagicMock()
        serial_repo.find_serials_of_unknown_type.return_value = [(1, "S1")]
        with _bound(serial_repo):
            serials_mod.run_enrich_serials_from_openalex(
                MagicMock(),
                MagicMock(),
                fetch_batch=lambda _oa_ids: {"S1": answer},
            )
        return serial_repo

    def test_mapped_type_is_written(self):
        repo = self._run("journal")
        repo.set_serial_type.assert_called_once_with(1, "journal")

    def test_type_without_signal_is_not_written(self):
        repo = self._run("other")
        repo.set_serial_type.assert_not_called()


class TestSerialsWorkerStopsOnTrippedBreaker:
    def _run(self, fetch_batch, n_batches):
        conn = MagicMock()
        serial_repo = MagicMock()
        # Ligne : (serial_id, identifiant OpenAlex) ; BATCH_SIZE revues par lot.
        rows = [(i, f"S{i}") for i in range(n_batches * serials_mod.BATCH_SIZE)]
        serial_repo.find_serials_of_unknown_type.return_value = rows
        with _bound(serial_repo), source_circuit_breaker("openalex"):
            serials_mod.run_enrich_serials_from_openalex(conn, MagicMock(), fetch_batch=fetch_batch)
        return conn

    def test_stops_when_breaker_trips(self):
        """Le worker s'arrête au tour qui suit la coupure du circuit-breaker, sans parcourir toutes les revues."""
        calls = {"n": 0}

        def fetch_batch(_oa_ids):
            calls["n"] += 1
            if calls["n"] >= 3 and (breaker := get_current_breaker()) is not None:
                breaker.tripped = True  # le troisième lot coupe le circuit-breaker
            return {}

        conn = self._run(fetch_batch, n_batches=20)
        assert calls["n"] == 3  # arrêt après le troisième lot, sur vingt
        conn.commit.assert_called()  # le travail fait est commité avant l'arrêt

    def test_runs_all_batches_when_breaker_stays_up(self):
        """Sans coupure du circuit-breaker, tous les lots sont parcourus."""
        calls = {"n": 0}

        def fetch_batch(_oa_ids):
            calls["n"] += 1
            return {}

        self._run(fetch_batch, n_batches=4)
        assert calls["n"] == 4
