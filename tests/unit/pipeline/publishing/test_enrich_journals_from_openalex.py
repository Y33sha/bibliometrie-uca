"""Enrichissement des revues par OpenAlex Sources : écriture de l'APC et du type."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pipeline.publishing.journals import enrich_journals_from_openalex as journals_mod


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(journals_mod.time, "sleep", lambda *_: None)


class TestJournalsApc:
    def _run(self, answer):
        journal_repo = MagicMock()
        journal_repo.find_journals_of_unknown_type.return_value = [(1, "S1")]
        journals_mod.run_enrich_journals_from_openalex(
            MagicMock(),
            MagicMock(),
            journal_repo=journal_repo,
            fetch_batch=lambda _oa_ids: {"S1": answer},
            breaker=SimpleNamespace(tripped=False),
        )
        return journal_repo

    def test_apc_found_is_written(self):
        repo = self._run((1500.0, "USD", "journal"))
        repo.update_journal_apc.assert_called_once_with(1, apc_amount=1500.0, apc_currency="USD")

    def test_no_apc_leaves_journal_apc_unchanged(self):
        """Sans APC dans OpenAlex, ni montant ni devise ne sont écrits ; le type l'est."""
        repo = self._run((None, None, "journal"))
        repo.update_journal_apc.assert_not_called()
        repo.set_journal_type.assert_called_once()


class TestJournalsWorkerStopsOnTrippedBreaker:
    def _run(self, fetch_batch, breaker, n_batches):
        conn = MagicMock()
        journal_repo = MagicMock()
        # row = (journal_id, oa_id) ; BATCH_SIZE journaux par batch.
        rows = [(i, f"S{i}") for i in range(n_batches * journals_mod.BATCH_SIZE)]
        journal_repo.find_journals_of_unknown_type.return_value = rows
        journals_mod.run_enrich_journals_from_openalex(
            conn,
            MagicMock(),
            journal_repo=journal_repo,
            fetch_batch=fetch_batch,
            breaker=breaker,
        )
        return conn

    def test_stops_when_breaker_trips(self):
        """Le worker s'arrête au tour où le breaker est tripé, sans parcourir tout le stock."""
        breaker = SimpleNamespace(tripped=False)
        calls = {"n": 0}

        def fetch_batch(_oa_ids):
            calls["n"] += 1
            if calls["n"] >= 3:
                breaker.tripped = True  # le 3e batch épuise le budget
            return {}

        conn = self._run(fetch_batch, breaker, n_batches=20)
        assert calls["n"] == 3  # arrêt au tour suivant (breaker.tripped), pas les 20 batches
        conn.commit.assert_called()  # le déjà-fait est committé avant de couper

    def test_runs_all_batches_when_breaker_stays_up(self):
        """Sans trip, tous les batches sont parcourus."""
        breaker = SimpleNamespace(tripped=False)
        calls = {"n": 0}

        def fetch_batch(_oa_ids):
            calls["n"] += 1
            return {}

        self._run(fetch_batch, breaker, n_batches=4)
        assert calls["n"] == 4
