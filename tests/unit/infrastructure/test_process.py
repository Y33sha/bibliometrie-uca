"""Sonde de vivacité d'un processus, dont dépend le verrou du pipeline.

Deux exécutions concurrentes du pipeline se bloquent l'une l'autre en base : le verrou retient le numéro du processus qui le détient, et sa levée dépend de cette sonde. Se tromper dans un sens laisse un verrou orphelin bloquer indéfiniment ; se tromper dans l'autre laisse démarrer un second pipeline.
"""

import os

import pytest

from infrastructure.process import is_pid_alive


def test_le_processus_courant_est_vivant():
    assert is_pid_alive(os.getpid()) is True


@pytest.mark.parametrize("pid", [0, -1])
def test_numero_invalide(pid):
    """Un numéro nul ou négatif désigne, pour le système, autre chose qu'un processus."""
    assert is_pid_alive(pid) is False


def test_processus_disparu(monkeypatch):
    def _disparu(pid, signal):
        raise ProcessLookupError

    monkeypatch.setattr(os, "kill", _disparu)
    assert is_pid_alive(4242) is False


def test_processus_d_un_autre_compte(monkeypatch):
    """Interroger un processus d'un autre utilisateur est refusé : le refus prouve qu'il existe."""

    def _refuse(pid, signal):
        raise PermissionError

    monkeypatch.setattr(os, "kill", _refuse)
    assert is_pid_alive(4242) is True
