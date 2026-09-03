"""Trajet de `--no-raw-store` jusqu'au choix du store de payloads bruts.

Le drapeau descend du composition root à la phase de normalisation, seule à écrire dans le store. Sans archivage, le store sur disque n'est pas même construit.
"""

import pytest

from infrastructure.raw_store import LocalFileRawStore
from interfaces.cli import run_pipeline


def test_sans_archivage_le_store_disque_n_est_pas_construit(monkeypatch):
    def _interdit(*args, **kwargs):
        pytest.fail("le store sur disque ne doit pas être construit sans archivage")

    monkeypatch.setattr("infrastructure.raw_store.get_raw_store", _interdit)
    assert run_pipeline._normalize_builders(archive=False)


def test_avec_archivage_le_store_disque_est_construit(monkeypatch):
    obtenus = []
    monkeypatch.setattr(
        "infrastructure.raw_store.get_raw_store",
        lambda *a, **k: obtenus.append(True) or LocalFileRawStore("/tmp/inexistant"),
    )
    run_pipeline._normalize_builders(archive=True)
    assert obtenus == [True]


def test_le_defaut_archive(monkeypatch):
    # Sans drapeau, le comportement d'archivage est conservé.
    obtenus = []
    monkeypatch.setattr(
        "infrastructure.raw_store.get_raw_store",
        lambda *a, **k: obtenus.append(True) or LocalFileRawStore("/tmp/inexistant"),
    )
    run_pipeline._normalize_builders()
    assert obtenus == [True]
