"""Coupe-circuit OpenAlex : arrêt de l'enrichissement quand la source est à bout de budget (429).

Les enrichissements des revues et des éditeurs s'appuient sur le même circuit-breaker de source :
le fetch (infra) l'alimente via `http_request_with_retry`, et la boucle de l'orchestrateur s'arrête
dès que `breaker.tripped`. On teste ici cet arrêt, et le parcours complet quand la source tient.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from application.pipeline.publishers_journals import enrich_journals_from_openalex as journals_mod
from application.services.publishers import enrich_country as publishers_mod


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Neutralise les backoffs pour des tests instantanés."""
    monkeypatch.setattr(journals_mod.time, "sleep", lambda *_: None)
    monkeypatch.setattr(publishers_mod.time, "sleep", lambda *_: None)


class TestPublishersWorkerStopsOnTrippedBreaker:
    def _run(self, fetch_batch, breaker, n_batches):
        conn = MagicMock()
        publisher_repo = MagicMock()
        # row = (publisher_id, oa_id) ; BATCH_SIZE éditeurs par batch.
        rows = [(i, f"P{i}") for i in range(n_batches * publishers_mod.BATCH_SIZE)]
        publisher_repo.find_needing_country_enrichment.return_value = rows
        publishers_mod.run_enrich_publishers_from_openalex(
            conn,
            MagicMock(),
            publisher_repo=publisher_repo,
            fetch_batch=fetch_batch,
            breaker=breaker,
        )
        return conn

    def test_stops_when_breaker_trips(self):
        """L'orchestrateur s'arrête au tour où le breaker est tripé, sans parcourir tout le stock."""
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
