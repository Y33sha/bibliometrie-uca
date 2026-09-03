"""Doublures partagées par les tests des orchestrateurs de phase.

Un orchestrateur de phase ne connaît ni la base ni les adapters : il reçoit un `OpenTransaction` et des ports. Ces doublures les remplacent, ce qui permet d'exercer l'enchaînement des sous-étapes, les métriques assemblées et les bornes de boucle sans base de données.
"""

from contextlib import contextmanager

import pytest


class FakeConnection:
    """Connexion inerte, qui retient ses commits."""

    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class FakeOpenTransaction:
    """Satisfait `OpenTransaction` : chaque appel ouvre une transaction sur la même connexion.

    Le nombre de transactions ouvertes est retenu : une phase qui doit isoler ses sous-étapes les unes des autres l'affirme en le comptant.
    """

    def __init__(self) -> None:
        self.conn = FakeConnection()
        self.transactions = 0

    @contextmanager
    def __call__(self):
        self.transactions += 1
        yield self.conn


@pytest.fixture
def open_tx() -> FakeOpenTransaction:
    return FakeOpenTransaction()
