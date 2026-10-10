"""Rafraîchissement du référentiel DOAJ (`run_enrich_journals_from_doaj`) : le dump est téléchargé seulement quand le dernier import date de plus que le délai."""

import logging
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from application.pipeline.publishers_journals.import_journals_from_doaj_dump import (
    run_enrich_journals_from_doaj,
)
from application.ports.pipeline.dump import DumpUnavailableError


class _FakeJournalRepo:
    def __init__(self, last_import_at: datetime | None) -> None:
        self.last_import_at = last_import_at
        self.updated: list[int] = []

    def doaj_last_import_at(self) -> datetime | None:
        return self.last_import_at

    def find_journal_issn_index(self) -> list[tuple[int, str]]:
        return [(1, "0028-0836")]

    def reset_is_in_doaj(self) -> int:
        return 0

    def update_journal_doaj(self, journal_id, *, payload, imported_at, is_in_doaj) -> None:
        self.updated.append(journal_id)


def _run(repo: _FakeJournalRepo) -> tuple[dict, list[bool]]:
    downloads: list[bool] = []

    @contextmanager
    def download_dump():
        downloads.append(True)
        yield [{"Journal ISSN (print version)": "0028-0836"}]

    metrics = run_enrich_journals_from_doaj(
        MagicMock(),
        logging.getLogger("test"),
        journal_repo=repo,
        refresh_after_days=30,
        download_dump=download_dump,
    )
    return metrics.extras, downloads


def test_recent_import_skips_download():
    repo = _FakeJournalRepo(datetime.now(UTC) - timedelta(days=10))
    extras, downloads = _run(repo)
    assert extras == {"skipped": 1}
    assert downloads == []


def test_stale_import_downloads_and_imports():
    repo = _FakeJournalRepo(datetime.now(UTC) - timedelta(days=40))
    extras, downloads = _run(repo)
    assert extras == {"matched": 1}
    assert downloads == [True]
    assert repo.updated == [1]


def test_first_import_downloads():
    extras, downloads = _run(_FakeJournalRepo(None))
    assert extras == {"matched": 1}
    assert downloads == [True]


def test_unavailable_dump_leaves_referential_unchanged():
    """Dump inaccessible : aucune écriture, la source est signalée indisponible et la phase continue."""

    class _Repo(_FakeJournalRepo):
        resets = 0

        def reset_is_in_doaj(self) -> int:
            type(self).resets += 1
            return 0

    @contextmanager
    def download_dump():
        raise DumpUnavailableError("HTTP 503")
        yield []

    repo = _Repo(None)
    metrics = run_enrich_journals_from_doaj(
        MagicMock(),
        logging.getLogger("test"),
        journal_repo=repo,
        refresh_after_days=30,
        download_dump=download_dump,
    )
    assert _Repo.resets == 0
    assert repo.updated == []
    assert [s["code"] for s in metrics.signals] == ["source_unavailable"]
