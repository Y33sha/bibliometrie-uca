"""Trajet de `--raw-store` jusqu'au choix du store de payloads bruts.

Le drapeau descend des options du run à la phase de normalisation, seule à écrire dans le store. Le store sur disque est construit seulement avec l'archivage.
"""

import logging
from unittest.mock import MagicMock

import pytest

from infrastructure.raw_store import LocalFileRawStore
from pipeline.ingestion.common import normalize


def _normaliseur(**archivage: bool) -> None:
    normalize.build_normalizer("hal", MagicMock(), logging.getLogger("test"), **archivage)


def test_sans_archivage_le_store_disque_n_est_pas_construit(monkeypatch):
    def _interdit(*args, **kwargs):
        pytest.fail("le store sur disque ne doit pas être construit sans archivage")

    monkeypatch.setattr("pipeline.ingestion.common.normalize.get_raw_store", _interdit)
    _normaliseur(archive=False)


def test_avec_archivage_le_store_disque_est_construit(monkeypatch):
    obtenus = []
    monkeypatch.setattr(
        "pipeline.ingestion.common.normalize.get_raw_store",
        lambda *a, **k: obtenus.append(True) or LocalFileRawStore("/tmp/inexistant"),
    )
    _normaliseur(archive=True)
    assert obtenus == [True]


def test_le_defaut_archive(monkeypatch):
    # Par défaut, la normalisation archive les payloads.
    obtenus = []
    monkeypatch.setattr(
        "pipeline.ingestion.common.normalize.get_raw_store",
        lambda *a, **k: obtenus.append(True) or LocalFileRawStore("/tmp/inexistant"),
    )
    _normaliseur()
    assert obtenus == [True]
