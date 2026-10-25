"""Rafraîchissement du référentiel DOAJ (`run_enrich_serials_from_doaj`) : le dump est téléchargé seulement quand le dernier import date de plus que le délai."""

import contextlib
import logging
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from pipeline.http.dump_download import DumpUnavailableError
from pipeline.transformation.publishing.serials import enrich_serials_from_doaj as step


class _FakeSerialRepo:
    def __init__(self, last_import_at: datetime | None) -> None:
        self.last_import_at = last_import_at
        self.updated: list[int] = []

    def doaj_last_import_at(self) -> datetime | None:
        return self.last_import_at

    def find_serial_issn_index(self) -> list[tuple[int, str]]:
        return [(1, "0028-0836")]

    def reset_is_in_doaj(self) -> int:
        return 0

    def update_serial_doaj(self, serial_id, *, payload, imported_at, is_in_doaj) -> None:
        self.updated.append(serial_id)


@contextlib.contextmanager
def _bound(repo):
    """Branche les fonctions SQL du module, et son store des revues, sur le faux `repo`."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            step, "doaj_last_import_at", lambda conn, *a, **k: repo.doaj_last_import_at(*a, **k)
        )
        mp.setattr(
            step,
            "find_serial_issn_index",
            lambda conn, *a, **k: repo.find_serial_issn_index(*a, **k),
        )
        mp.setattr(step, "reset_is_in_doaj", lambda conn, *a, **k: repo.reset_is_in_doaj(*a, **k))
        mp.setattr(
            step, "update_serial_doaj", lambda conn, *a, **k: repo.update_serial_doaj(*a, **k)
        )
        yield


def _run(repo: _FakeSerialRepo) -> tuple[dict, list[bool]]:
    downloads: list[bool] = []

    @contextmanager
    def download_dump():
        downloads.append(True)
        yield [{"Journal ISSN (print version)": "0028-0836"}]

    with _bound(repo):
        metrics = step.run_enrich_serials_from_doaj(
            MagicMock(),
            logging.getLogger("test"),
            refresh_after_days=30,
            download_dump=download_dump,
        )
    return metrics.extras, downloads


def test_recent_import_skips_download():
    repo = _FakeSerialRepo(datetime.now(UTC) - timedelta(days=10))
    extras, downloads = _run(repo)
    assert extras == {"skipped": 1}
    assert downloads == []


def test_stale_import_downloads_and_imports():
    repo = _FakeSerialRepo(datetime.now(UTC) - timedelta(days=40))
    extras, downloads = _run(repo)
    assert extras == {"matched": 1}
    assert downloads == [True]
    assert repo.updated == [1]


def test_first_import_downloads():
    extras, downloads = _run(_FakeSerialRepo(None))
    assert extras == {"matched": 1}
    assert downloads == [True]


def test_dump_without_recognized_serial_is_signaled():
    """Aucune revue reconnue : rien n'est écrit, la sous-étape le signale."""

    @contextmanager
    def download_dump():
        yield [{"Colonne renommée": "0028-0836"}]

    repo = _FakeSerialRepo(None)
    with _bound(repo):
        metrics = step.run_enrich_serials_from_doaj(
            MagicMock(),
            logging.getLogger("test"),
            refresh_after_days=30,
            download_dump=download_dump,
        )
    assert repo.updated == []
    assert [s["code"] for s in metrics.signals] == ["dump_unrecognized"]


def test_unavailable_dump_leaves_referential_unchanged():
    """Dump inaccessible : aucune écriture, la source est signalée indisponible et la phase continue."""

    class _Repo(_FakeSerialRepo):
        resets = 0

        def reset_is_in_doaj(self) -> int:
            type(self).resets += 1
            return 0

    @contextmanager
    def download_dump():
        raise DumpUnavailableError("HTTP 503")
        yield []

    repo = _Repo(None)
    with _bound(repo):
        metrics = step.run_enrich_serials_from_doaj(
            MagicMock(),
            logging.getLogger("test"),
            refresh_after_days=30,
            download_dump=download_dump,
        )
    assert _Repo.resets == 0
    assert repo.updated == []
    assert [s["code"] for s in metrics.signals] == ["source_unavailable"]
