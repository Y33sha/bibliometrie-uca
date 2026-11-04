"""Tests de la suppression des revues vides (`pipeline.transformation.publishing.serials.delete_empty_serials`)."""

import contextlib
import logging

import pytest

from pipeline.transformation.publishing.serials import delete_empty_serials as step
from pipeline.transformation.publishing.serials.store import SerialSummary


class _Repo:
    def __init__(self, deleted: list[SerialSummary]) -> None:
        self._deleted = deleted

    def delete_empty_serials(self) -> list[SerialSummary]:
        return self._deleted


@contextlib.contextmanager
def _bound(repo):
    """Branche les fonctions SQL du module, et son store des revues, sur le faux `repo`."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            step, "delete_empty_serials", lambda conn, *a, **k: repo.delete_empty_serials(*a, **k)
        )
        yield


def test_each_deleted_serial_is_counted():
    logger = logging.getLogger("test_revues_vides")
    deleted = [SerialSummary(101021, "Livestock Science", "IntechOpen", ())]
    with _bound(_Repo(deleted)):
        metrics = step.run_delete_empty_serials(None, logger)
    assert metrics.extras["serials_deleted"] == 1


def test_without_empty_serial_nothing_is_counted():
    logger = logging.getLogger("test_revues_vides_aucune")
    with _bound(_Repo([])):
        metrics = step.run_delete_empty_serials(None, logger)
    assert metrics.total == 0
