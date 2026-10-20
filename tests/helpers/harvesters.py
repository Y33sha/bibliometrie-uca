"""Moissonneur sur un client simulé, et arguments de son run, pour les tests des moissonneurs."""

import argparse
import logging
from collections.abc import Callable
from unittest.mock import MagicMock


def moissonneur[E](cls: Callable[..., E], client: MagicMock) -> E:
    """Moissonneur `cls` sur le client `client` et une connexion simulée."""
    return cls(MagicMock(), logging.getLogger("test"), client)


def source_a_bout() -> MagicMock:
    """Circuit-breaker déclenché."""
    return MagicMock(tripped=True)


def arguments_du_run(**surcharges: object) -> argparse.Namespace:
    """Arguments du run lus par les moissonneurs : année, année de début, date de dernière extraction, `None` par défaut."""
    return argparse.Namespace(**({"year": None, "start_year": None, "since": None} | surcharges))
