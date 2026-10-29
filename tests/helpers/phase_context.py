"""Doublures partagées par les tests des orchestrateurs de phase, importées par les `conftest.py` de leurs répertoires.

Un orchestrateur de phase reçoit un `OpenTransaction` et des ports. Ces doublures en tiennent lieu : les tests exercent l'enchaînement des sous-étapes, les métriques assemblées et les bornes de boucle sans base de données.
"""

import logging
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

import pytest

from pipeline.runtime.context import CredentialsMissing, PhaseContext, RunOptions


class FakeConnection:
    """Connexion inerte, qui retient ses commits."""

    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class FakeOpenTransaction:
    """Satisfait `OpenTransaction` : chaque appel ouvre une transaction sur la même connexion.

    Le nombre de transactions ouvertes est retenu : un test vérifie ainsi qu'une phase isole ses sous-étapes dans des transactions distinctes.
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


@pytest.fixture
def contexte(open_tx: FakeOpenTransaction) -> Callable[..., PhaseContext]:
    """Fabrique le contexte d'une phase sur `open_tx`, avec les options du run passées en arguments.

    Toutes les sources ont leurs identifiants de connexion, sauf contrôle `credentials_missing` fourni.
    """

    def fabriquer(
        *, credentials_missing: CredentialsMissing = lambda _source: None, **options: Any
    ) -> PhaseContext:
        return PhaseContext(
            open_tx=open_tx,
            logger=logging.getLogger("test"),
            options=RunOptions(**options),
            maintain=lambda operation: None,
            credentials_missing=credentials_missing,
            request_budget=lambda _source: None,
        )

    return fabriquer
