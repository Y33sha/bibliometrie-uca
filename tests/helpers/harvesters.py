"""Moissonneur sur un client simulé, et fenêtre de son run, pour les tests des moissonneurs."""

import logging
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

from pipeline.ingestion.common.harvester import HarvestWindow


def moissonneur[E](cls: Callable[..., E], client: MagicMock) -> E:
    """Moissonneur `cls` sur le client `client` et une connexion simulée."""
    return cls(MagicMock(), logging.getLogger("test"), client)


def arguments_du_run(**surcharges: Any) -> HarvestWindow:
    """Fenêtre du moissonnage : année, année de début, date de modification minimale, `None` par défaut."""
    return HarvestWindow(**surcharges)
