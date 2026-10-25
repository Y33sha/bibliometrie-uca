"""Tests du calcul des espaces de noms DOI des revues (`pipeline.transformation.publishing.serials.learn_serial_doi_namespaces`)."""

import contextlib
import logging
from collections.abc import Sequence

import pytest

from domain.serials.doi_namespaces import DoiNamespace
from domain.serials.serial import SerialType
from pipeline.transformation.publishing.serials import learn_serial_doi_namespaces as step
from pipeline.transformation.publishing.serials.learn_serial_doi_namespaces import DoiSerialRow


class _Repo:
    def __init__(self, pairs: list[DoiSerialRow]) -> None:
        self._pairs = pairs
        self.stored: list[DoiNamespace] = []

    def find_doi_serial_pairs(self) -> list[DoiSerialRow]:
        return self._pairs

    def store_doi_namespaces(self, namespaces: Sequence[DoiNamespace]) -> None:
        self.stored = list(namespaces)


@contextlib.contextmanager
def _bound(repo):
    """Branche les fonctions SQL du module, et son store des revues, sur le faux `repo`."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            step,
            "find_doi_serial_pairs",
            lambda conn, *a, **k: repo.find_doi_serial_pairs(*a, **k),
        )
        mp.setattr(
            step, "store_doi_namespaces", lambda conn, *a, **k: repo.store_doi_namespaces(*a, **k)
        )
        yield


def _pairs(prefix: str, serial_id: int, serial_type: SerialType) -> list[DoiSerialRow]:
    return [DoiSerialRow(f"{prefix}{i:05d}", serial_id, serial_type) for i in range(10)]


def test_une_plateforme_n_obtient_aucun_espace():
    repo = _Repo(
        _pairs("10.64628/aak.", 1, SerialType.MEDIA)
        + _pairs("10.2139/ssrn.", 2, SerialType.REPOSITORY)
    )
    with _bound(repo):
        metrics = step.run_learn_serial_doi_namespaces(None, logging.getLogger("test"))
    assert [(ns.namespace, ns.serial_id) for ns in repo.stored] == [("10.64628/aak.", 1)]
    assert metrics.extras["serial_doi_namespaces"] == 1
