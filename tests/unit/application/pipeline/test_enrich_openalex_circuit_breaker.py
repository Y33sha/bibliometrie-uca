"""Régression : coupe-circuit OpenAlex sur 429 répétés (budget API quotidien épuisé).

Avant le fix, un batch en 429 (3 retries épuisés) retournait `{}` silencieusement et la
boucle avançait sur tout le stock en cramant le budget. Désormais le fetch lève
`_OpenAlexRateLimited`, et la passe coupe après `RATE_LIMIT_STRIKES_MAX` strikes
consécutifs (le compteur se remet à zéro sur tout batch non rate-limité).

Symétrie : `enrich_publishers_from_openalex` a la même logique ; on teste ici les deux
helpers `fetch_*` et la boucle `run_enrich_journals_from_openalex` (représentative).
"""

from unittest.mock import MagicMock

import pytest

from application.pipeline.publishers_journals import enrich_journals_from_openalex as journals_mod
from application.services.publishers.enrichment import from_openalex as publishers_mod


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Neutralise les backoffs (2+4+8s) pour des tests instantanés."""
    monkeypatch.setattr(journals_mod.time, "sleep", lambda *_: None)
    monkeypatch.setattr(publishers_mod.time, "sleep", lambda *_: None)


def _resp(status, payload=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload or {"results": []}
    return r


class TestFetchSignalsRateLimit:
    def test_sustained_429_raises(self, monkeypatch):
        """3 × 429 → `_OpenAlexRateLimited` (au lieu du `{}` silencieux d'avant)."""
        monkeypatch.setattr(journals_mod.requests, "get", lambda *a, **k: _resp(429))
        with pytest.raises(journals_mod._OpenAlexRateLimited):
            journals_mod.fetch_sources_batch(
                ["S1"], MagicMock(), openalex_sources_api="x", api_key=None, mailto="m"
            )

    def test_success_returns_data(self, monkeypatch):
        payload = {"results": [{"id": "https://openalex.org/S1", "type": "journal"}]}
        monkeypatch.setattr(journals_mod.requests, "get", lambda *a, **k: _resp(200, payload))
        out = journals_mod.fetch_sources_batch(
            ["S1"], MagicMock(), openalex_sources_api="x", api_key=None, mailto="m"
        )
        assert out == {"S1": {"id": "https://openalex.org/S1", "type": "journal"}}

    def test_publishers_sustained_429_raises(self, monkeypatch):
        monkeypatch.setattr(publishers_mod.requests, "get", lambda *a, **k: _resp(429))
        with pytest.raises(publishers_mod._OpenAlexRateLimited):
            publishers_mod.fetch_publishers_batch(
                ["P1"], MagicMock(), openalex_publishers_api="x", api_key=None, mailto="m"
            )


class TestRunCircuitBreaks:
    def _run(self, monkeypatch, fetch_side_effect, n_batches):
        calls = {"n": 0}

        def fake_fetch(*_a, **_k):
            i = calls["n"]
            calls["n"] += 1
            outcome = fetch_side_effect(i)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        monkeypatch.setattr(journals_mod, "fetch_sources_batch", fake_fetch)
        conn = MagicMock()
        queries = MagicMock()
        # row = (journal_id, oa_id) ; BATCH_SIZE journaux par batch.
        rows = [(i, f"S{i}") for i in range(n_batches * journals_mod.BATCH_SIZE)]
        queries.fetch_journals_of_unknown_type.return_value = rows

        journals_mod.run_enrich_journals_from_openalex(
            conn,
            queries,
            MagicMock(),
            journal_repo=MagicMock(),
            api_key=None,
            mailto="m",
            openalex_sources_api="x",
        )
        return calls["n"], conn

    def test_aborts_after_max_consecutive_strikes(self, monkeypatch):
        """Tout en 429 → coupe après RATE_LIMIT_STRIKES_MAX batches, pas tout le stock."""
        n_calls, conn = self._run(
            monkeypatch,
            lambda _i: journals_mod._OpenAlexRateLimited(),
            n_batches=20,
        )
        assert n_calls == journals_mod.RATE_LIMIT_STRIKES_MAX
        conn.commit.assert_called()  # le déjà-fait est committé avant de couper

    def test_strike_counter_resets_on_success(self, monkeypatch):
        """Un batch réussi entre deux séries de 429 remet le compteur à zéro."""
        rl = journals_mod._OpenAlexRateLimited
        # strikes 1,2 → succès (reset) → 1,2,3 → coupe au 6e appel.
        seq = [rl(), rl(), {}, rl(), rl(), rl()]
        n_calls, _ = self._run(monkeypatch, lambda i: seq[i], n_batches=len(seq))
        assert n_calls == 6  # pas coupé à 3 grâce au reset
