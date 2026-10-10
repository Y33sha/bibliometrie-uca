"""Enrichissement des revues par OpenAlex Sources : écriture de l'APC et du type."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from application.pipeline.publishers_journals import enrich_journals_from_openalex as journals_mod


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
